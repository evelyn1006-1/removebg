import io
import gc
import hashlib
import hmac
import os
import time
import unicodedata
import uuid
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from PIL import Image
from rembg import new_session, remove
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "change-me")
ALLOWED_HOSTS = {
    h.strip().lower()
    for h in os.getenv(
        "ALLOWED_HOSTS",
        "removebg.princessevelyn.com,localhost,127.0.0.1",
    ).split(",")
    if h.strip()
}

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "u2net")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
MAX_DIM = int(os.getenv("MAX_DIM", "3840"))
OUTPUT_TTL_SECONDS = int(os.getenv("OUTPUT_TTL_SECONDS", "900"))
MAX_FILES = int(os.getenv("MAX_FILES", "8"))
MAX_MODEL_THREADS = int(os.getenv("MAX_MODEL_THREADS", "4"))
HEAVY_MODEL_PASSPHRASE_HASH = os.getenv(
    "HEAVY_MODEL_PASSPHRASE_HASH",
    "change-me",
)

MODEL_LABELS = {
    "u2net": "u2net (general)",
    "u2netp": "u2netp (fast)",
    "silueta": "silueta (small)",
    "u2net_human_seg": "u2net_human_seg (portraits)",
    "u2net_cloth_seg": "u2net_cloth_seg (clothing)",
    "isnet-anime": "isnet-anime (cartoon/anime)",
    "isnet-general-use": "isnet-general-use (general)",
    "birefnet-general-lite": "birefnet-general-lite (high quality)",
}
HEAVY_MODEL_LABELS = {
    "birefnet-general": "birefnet-general (ultra)",
    "birefnet-portrait": "birefnet-portrait (ultra portraits)",
    "bria-rmbg": "bria-rmbg (ultra)",
}
ALLOWED_MODELS = list(MODEL_LABELS.keys()) + list(HEAVY_MODEL_LABELS.keys())
HEAVY_MODELS = set(HEAVY_MODEL_LABELS.keys())

UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

processing_lock = Lock()

ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def configure_model_threads() -> None:
    if MAX_MODEL_THREADS <= 0:
        return
    current = os.getenv("OMP_NUM_THREADS")
    if not (current and current.isdigit()):
        current = MAX_MODEL_THREADS
    os.environ["OMP_NUM_THREADS"] = str(current)

configure_model_threads()


def get_request_host() -> str:
    host = request.host or ""
    return host.split(":")[0].lower()


def is_safe_host(host: str) -> bool:
    return host in ALLOWED_HOSTS


def cleanup_outputs() -> None:
    now = time.time()
    for path in OUTPUT_DIR.glob("*.png"):
        try:
            if now - path.stat().st_mtime > OUTPUT_TTL_SECONDS:
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
    for path in OUTPUT_DIR.glob("batch_*.json"):
        try:
            if now - path.stat().st_mtime > OUTPUT_TTL_SECONDS:
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass


def resize_if_needed(image_bytes: bytes) -> bytes:
    if MAX_DIM <= 0:
        return image_bytes
    with Image.open(io.BytesIO(image_bytes)) as img:
        if max(img.size) <= MAX_DIM:
            return image_bytes
        img = img.convert("RGBA")
        img.thumbnail((MAX_DIM, MAX_DIM), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def passphrase_digest(passphrase: str) -> str:
    normalized = unicodedata.normalize("NFC", passphrase)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def is_heavy_model_passphrase_valid(passphrase: str) -> bool:
    return hmac.compare_digest(
        passphrase_digest(passphrase),
        HEAVY_MODEL_PASSPHRASE_HASH.lower(),
    )


def create_app() -> Flask:
    app = Flask(__name__)
    if FLASK_SECRET_KEY:
        app.config["SECRET_KEY"] = FLASK_SECRET_KEY
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=MAX_UPLOAD_MB * 1024 * 1024,
        DEFAULT_MODEL=DEFAULT_MODEL,
        MAX_DIM=MAX_DIM,
        MAX_FILES=MAX_FILES,
        MODEL_OPTIONS=MODEL_LABELS,
        HEAVY_MODEL_OPTIONS=HEAVY_MODEL_LABELS,
        HEAVY_MODEL_KEYS=list(HEAVY_MODEL_LABELS.keys()),
    )

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    def get_session(model: str):
        try:
            return new_session(model)
        except Exception as exc:
            app.logger.error("Failed to initialize model %s: %s", model, exc)
            return None

    @app.before_request
    def enforce_host_check() -> None:
        if ALLOWED_HOSTS and not is_safe_host(get_request_host()):
            abort(400)
        cleanup_outputs()

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = (
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "base-uri 'self'"
        )
        return response

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/")
    def process_image():
        if not processing_lock.acquire(blocking=False):
            flash("Busy right now. Try again in a moment.")
            return render_template("index.html"), 503

        session = None
        try:
            model = request.form.get("model", DEFAULT_MODEL)
            if model not in ALLOWED_MODELS:
                model = DEFAULT_MODEL
            if model in HEAVY_MODELS and not is_heavy_model_passphrase_valid(
                request.form.get("heavy_model_passphrase", "")
            ):
                flash("That model needs the heavy-model passphrase.")
                return render_template("index.html"), 403
            session = get_session(model)
            if session is None:
                flash("Model failed to initialize. Check server logs.")
                return render_template("index.html"), 500

            uploads = request.files.getlist("images")
            if not uploads:
                single = request.files.get("image")
                if single:
                    uploads = [single]

            uploads = [u for u in uploads if u and u.filename]
            if not uploads:
                flash("Please choose at least one image to upload.")
                return render_template("index.html"), 400

            if len(uploads) > MAX_FILES:
                flash(f"Too many files. Limit is {MAX_FILES}.")
                return render_template("index.html"), 400

            file_ids = []
            for upload in uploads:
                filename = secure_filename(upload.filename)
                ext = os.path.splitext(filename)[1].lower()
                if ext not in ALLOWED_EXTS:
                    flash("Unsupported file type. Use PNG, JPG, or WebP.")
                    return render_template("index.html"), 400

                data = upload.read()
                if not data:
                    flash("Empty upload.")
                    return render_template("index.html"), 400

                data = resize_if_needed(data)
                output_bytes = remove(data, session=session)

                file_id = uuid.uuid4().hex
                output_path = OUTPUT_DIR / f"{file_id}.png"
                output_path.write_bytes(output_bytes)
                file_ids.append(file_id)

            if len(file_ids) == 1:
                return redirect(url_for("view_result", file_id=file_ids[0]))

            batch_id = uuid.uuid4().hex
            batch_path = OUTPUT_DIR / f"batch_{batch_id}.json"
            batch_path.write_text(
                "\n".join(file_ids),
                encoding="utf-8",
            )
            return redirect(url_for("view_batch", batch_id=batch_id))
        except Exception as exc:
            app.logger.exception("Background removal failed: %s", exc)
            flash("Background removal failed. Try a smaller image.")
            return render_template("index.html"), 500
        finally:
            del session
            gc.collect()
            processing_lock.release()

    @app.get("/view/<file_id>")
    def view_result(file_id: str):
        path = OUTPUT_DIR / f"{file_id}.png"
        if not path.exists():
            abort(404)
        return render_template("result.html", file_id=file_id)

    @app.get("/batch/<batch_id>")
    def view_batch(batch_id: str):
        path = OUTPUT_DIR / f"batch_{batch_id}.json"
        if not path.exists():
            abort(404)
        file_ids = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not file_ids:
            abort(404)
        return render_template("batch.html", file_ids=file_ids)

    @app.get("/result/<file_id>")
    def result_file(file_id: str):
        path = OUTPUT_DIR / f"{file_id}.png"
        if not path.exists():
            abort(404)
        return send_file(path, mimetype="image/png")

    @app.get("/download/<file_id>")
    def download_file(file_id: str):
        path = OUTPUT_DIR / f"{file_id}.png"
        if not path.exists():
            abort(404)
        return send_file(
            path,
            mimetype="image/png",
            as_attachment=True,
            download_name="removebg.png",
        )

    @app.get("/healthz")
    def healthz():
        return "ok", 200

    return app
