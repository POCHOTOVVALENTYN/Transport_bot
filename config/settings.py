import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ===============================================
# 1. НАЛАШТУВАННЯ БАЗИ ДАНИХ (УНІКАЛЬНЕ МІСЦЕ)
# ===============================================
DB_HOST = os.getenv("DB_HOST", "db")  # ⚠️ Всередину Docker: "db"
DB_USER = os.getenv("DB_USER", "bot_user")
DB_PASS = os.getenv("DB_PASS", "secure_pass")
DB_NAME = os.getenv("DB_NAME", "transport_bot_db")
DB_PORT = os.getenv("DB_PORT", "5432")  # ⚠️ Всередину контейнера: 5432

# Формуємо URL для SQLAlchemy (можна перевизначити через DATABASE_URL)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ===============================================
# 2. TELEGRAM НАЛАШТУВАННЯ
# ===============================================
DEBUG = os.getenv("DEBUG", "False") == "True"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEVELOPER_ID = int(os.getenv("DEVELOPER_ID", 0))
MUSEUM_ADMIN_ID = int(os.getenv("MUSEUM_ADMIN_ID", 0))
GENERAL_ADMIN_IDS = [
    830196453,  # Валентин
    384349401   # Тетяна
]

# ===============================================
# 3. GOOGLE SHEETS НАЛАШТУВАННЯ
# ===============================================
# ⚠️ ВАЖЛИВО: ЦЕ ПОТРІБНО ДЛЯ integrations/google_sheets/client.py
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "1kbQ_WuZy79xwGRXgCSIp-unBiGY42YQLH9V3zbqnoXo")
GOOGLE_SHEET_ID = GOOGLE_SHEETS_ID  # Альтернативна назва (для сумісності)
GOOGLE_SHEETS_CREDENTIALS_FILE = BASE_DIR / "integrations/google_sheets/credentials.json"

# ===============================================
# 4. ЛОГУВАННЯ
# ===============================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = BASE_DIR / "logs" / "bot.log"
FEEDBACK_SYNC_INTERVAL_MIN = int(os.getenv("FEEDBACK_SYNC_INTERVAL_MIN", "15"))

# ===============================================
# 5. ШЛЯХИ ДО ЗОБРАЖЕНЬ ТА ДОКУМЕНТІВ
# ===============================================
IMAGES_PATH = BASE_DIR / "assets" / "images"
DOCUMENTS_PATH = BASE_DIR / "documents"

# Зображення для квитків
TICKET_PASSES_IMAGE_1 = IMAGES_PATH / "passes_part_1.png"
TICKET_PASSES_IMAGE_2 = IMAGES_PATH / "passes_part_2.png"

TICKET_PASSES_FILE_ID_1 = "AgACAgIAAxkBAAIEL2kMn2UoUM2r0dc0GvTlXCax0L9hAAKJDWsbLpppSAxixJcLi4gSAQADAgADeQADNgQ"
TICKET_PASSES_FILE_ID_2 = "AgACAgIAAxkBAAIEMWkMn4t4dEJ9rOyVA-95XzsgsewJAAKSDWsbLpppSEMR6et11IqTAQADAgADeQADNgQ"

# PDF та інші документи
RULES_PDF_PATH = DOCUMENTS_PATH / "rules_of_use.pdf"
MUSEUM_LOGO_IMAGE = IMAGES_PATH / "museum_logo.png"
RENTAL_SERVICE_IMAGE = IMAGES_PATH / "rental_service.jpg"

# ===============================================
# 6. EASYWAY API НАЛАШТУВАННЯ
# ===============================================
EASYWAY_API_URL = "https://api.easyway.info"
EASYWAY_LOGIN = "odesainclusive"
EASYWAY_PASSWORD = "ndHdy2Ytw2Ois"
EASYWAY_CITY = "odesa"
EASYWAY_STOP_INFO_VERSION = "1.2"  # API версія з GPS

# Кешування EasyWay
EASYWAY_STOP_CACHE_TTL = int(os.getenv("EASYWAY_STOP_CACHE_TTL", "30"))
EASYWAY_PLACES_CACHE_TTL = int(os.getenv("EASYWAY_PLACES_CACHE_TTL", "120"))
EASYWAY_ROUTES_CACHE_TTL = int(os.getenv("EASYWAY_ROUTES_CACHE_TTL", "1800"))
EASYWAY_ROUTE_GPS_CACHE_TTL = int(os.getenv("EASYWAY_ROUTE_GPS_CACHE_TTL", "15"))

# Синхронізація звернень
FEEDBACK_SYNC_BATCH_SIZE = int(os.getenv("FEEDBACK_SYNC_BATCH_SIZE", "100"))
FEEDBACK_SYNC_MAX_ROWS = int(os.getenv("FEEDBACK_SYNC_MAX_ROWS", "500"))

# Розсилка
BROADCAST_BATCH_SIZE = int(os.getenv("BROADCAST_BATCH_SIZE", "50"))
BROADCAST_PAUSE_SEC = float(os.getenv("BROADCAST_PAUSE_SEC", "0.2"))

# Іконки для джерел часу
TIME_SOURCE_ICONS = {
    "gps": "🛰️",
    "schedule": "🗓️",
    "interval": "⏳",
    "unknown": "❓"
}