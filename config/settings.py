import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# --- НАЛАШТУВАННЯ БД ---
# Якщо ми в Docker, хост БД буде називатися "db" (як у docker-compose), інакше localhost
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "bot_user")
DB_PASS = os.getenv("DB_PASS", "secure_pass")
DB_NAME = os.getenv("DB_NAME", "transport_bot_db")
DB_PORT = os.getenv("DB_PORT", "5432")

# Формуємо URL для SQLAlchemy
DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# --- ІНШІ НАЛАШТУВАННЯ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Шлях до Google Credentials (має збігатися з тим, куди ми монтуємо volume в docker-compose)
CREDENTIALS_PATH = BASE_DIR / "config" / "google_credentials.json"

# Основні
BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv("DEBUG", "False") == "True"

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEVELOPER_ID = int(os.getenv("DEVELOPER_ID", 0))
MUSEUM_ADMIN_ID = int(os.getenv("MUSEUM_ADMIN_ID", 0))
GENERAL_ADMIN_IDS = [
    830196453,  # Валентин
    384349401   # Тетяна
]

# Google Sheets
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
CREDENTIALS_PATH = BASE_DIR / "integrations/google_sheets/credentials.json"


# Налаштування для Docker контейнера на порту 5433
DB_USER = os.getenv("DB_USER", "bot_user")
DB_PASS = os.getenv("DB_PASS", "secure_pass")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5433")  # <--- ВАЖЛИВО: ЗМІНИЛИ ТУТ НА 5433
DB_NAME = os.getenv("DB_NAME", "transport_bot_db")

# Postgres URL
DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = BASE_DIR / "logs" / "bot.log"

# Trapport routes


# ===== IMAGES PATH =====
IMAGES_PATH = BASE_DIR / "assets" / "images"

# Зображення для квитків
TICKET_PASSES_IMAGE_1 = IMAGES_PATH / "passes_part_1.png"
TICKET_PASSES_IMAGE_2 = IMAGES_PATH / "passes_part_2.png"

TICKET_PASSES_FILE_ID_1 = "AgACAgIAAxkBAAIEL2kMn2UoUM2r0dc0GvTlXCax0L9hAAKJDWsbLpppSAxixJcLi4gSAQADAgADeQADNgQ"
TICKET_PASSES_FILE_ID_2 = "AgACAgIAAxkBAAIEMWkMn4t4dEJ9rOyVA-95XzsgsewJAAKSDWsbLpppSEMR6et11IqTAQADAgADeQADNgQ"

# EasyWay API
EASYWAY_API_URL = "https://api.easyway.info"
EASYWAY_LOGIN = "odesainclusive"
EASYWAY_PASSWORD = "ndHdy2Ytw2Ois"
EASYWAY_CITY = "odesa"

# ⭐ НОВІ НАЛАШТУВАННЯ (v1.2)
EASYWAY_STOP_INFO_VERSION = "1.2"  # API версія з GPS

# Іконки для джерел часу
TIME_SOURCE_ICONS = {
    "gps": "🛰️",
    "schedule": "🗓️",
    "interval": "⏳",
    "unknown": "❓"
}

# ===== DOCUMENTS PATH =====
DOCUMENTS_PATH = BASE_DIR / "documents"
RULES_PDF_PATH = DOCUMENTS_PATH / "rules_of_use.pdf"

MUSEUM_LOGO_IMAGE = IMAGES_PATH / "museum_logo.png"

RENTAL_SERVICE_IMAGE = IMAGES_PATH / "rental_service.jpg"