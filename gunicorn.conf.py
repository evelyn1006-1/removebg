from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
IGNORE_DIR = LOG_DIR / "ignore"

LOG_DIR.mkdir(parents=True, exist_ok=True)
IGNORE_DIR.mkdir(parents=True, exist_ok=True)

# Server
bind = "127.0.0.1:8004"
workers = 1
timeout = 120
worker_class = "sync"
forwarded_allow_ips = "127.0.0.1"

# Logging
loglevel = "info"
capture_output = True

errorlog = str(LOG_DIR / "server.log")
accesslog = str(IGNORE_DIR / "access.log")
access_log_format = '%(h)s %(l)s %(u)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s'
