import os


def getenv(key: str, default: str = "") -> str:
    val = os.getenv(key)
    return val if val is not None and val != "" else default

def getint(key: str, default: int) -> int:
    val = os.getenv(key)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


API_KEY = getenv("APIKEY", "changeme")
CONVERT_TIMEOUT = getint("CONVERT_TIMEOUT", 600)
CPU_CORES_DEFAULT = max(1, os.cpu_count() or 2)
MAX_CONCURRENCY = getint("MAX_CONCURRENCY", CPU_CORES_DEFAULT)
CLEANUP_AFTER_SECONDS = getint("CLEANUP_AFTER_SECONDS", 3600)
LOG_DIR = getenv("LOG_DIR", "/tmp/o2plog")
DATA_DIR = getenv("DATA_DIR", "/tmp/o2pdata")

# Production hardening options
MAX_RETRIES = getint("MAX_RETRIES", 2)  # additional retries after first attempt
MAX_QUEUE_SIZE = getint("MAX_QUEUE_SIZE", 1000)  # 0 means unlimited
JOB_RECORD_TTL_SECONDS = getint("JOB_RECORD_TTL_SECONDS", 86400)  # default 1 day
LOG_MAX_BYTES = getint("LOG_MAX_BYTES", 10 * 1024 * 1024)  # 10MB
LOG_BACKUP_COUNT = getint("LOG_BACKUP_COUNT", 10)
LOG_LEVEL = getenv("LOG_LEVEL", "INFO")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)