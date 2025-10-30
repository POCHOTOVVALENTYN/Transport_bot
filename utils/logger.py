import logging
import logging.handlers
from pathlib import Path
from config.settings import LOG_FILE, LOG_LEVEL

# Створення папки логів
LOG_FILE.parent.mkdir(exist_ok=True)

# Налаштування logger
logger = logging.getLogger("transport_bot")
logger.setLevel(getattr(logging, LOG_LEVEL))

# File handler
file_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE,
    maxBytes=10485760,  # 10MB
    backupCount=5
)
file_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
file_handler.setFormatter(file_formatter)

# Console handler
console_handler = logging.StreamHandler()
console_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
console_handler.setFormatter(console_formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)