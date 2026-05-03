# Princess Evelyn RemoveBG

A small Flask app for removing image backgrounds with `rembg`. It supports single-image and small batch uploads, model selection, temporary output links, and a simple production deployment through Gunicorn, systemd, and Nginx.

## Requirements

- Python 3.11+
- `rembg[cpu]`
- Flask / Gunicorn

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

## Run Locally

```bash
python -m flask --app app run
```

Then open `http://127.0.0.1:5000`.

## Configuration

Heavy models require a passphrase. Set `HEAVY_MODEL_PASSPHRASE_HASH` to the
SHA-256 hex digest of the passphrase if you want to change it without editing
the app. Passphrases are normalized with Unicode NFC before hashing.

## Deploy

The `deploy/` folder contains the systemd service and Nginx site config used for `removebg.princessevelyn.com`.

Runtime uploads, generated outputs, logs, local env files, and caches are intentionally ignored by git.
