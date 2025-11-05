import logging
import os
from logging.handlers import RotatingFileHandler

from .config import LOG_DIR, LOG_MAX_BYTES, LOG_BACKUP_COUNT, LOG_LEVEL


def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    try:
        logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    except Exception:
        logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logfile = os.path.join(LOG_DIR, f"{name}.log")
    handler = RotatingFileHandler(logfile, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT)
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)
    return logger