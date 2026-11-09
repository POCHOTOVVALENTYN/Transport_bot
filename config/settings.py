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
MUSEUM_ADMIN_IDS = [
    MUSEUM_ADMIN_ID,
    5077309503
]
GENERAL_ADMIN_IDS = [
    830196453,  # Валентин
    1037495749  # Ірина Лісова
]
LEGACY_USERS_OFFSET = int(os.getenv("LEGACY_USERS_OFFSET", "400"))

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
RENTAL_RETRO_HUB_IMAGE = IMAGES_PATH / "rental_retro_hub.jpg"

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

# ===============================================
# 7. WIALON REMOTE API НАЛАШТУВАННЯ
# ===============================================
WIALON_HOST = os.getenv("WIALON_HOST", "https://hst-api.wialon.eu/wialon/ajax.html")
WIALON_TOKEN = os.getenv("WIALON_TOKEN", "9777076e141aeb12ca0154759bea4a7e1F6F8A7E4C3A54A318391BCDA4FE2F0342132072")
WIALON_TIMEOUT_SEC = int(os.getenv("WIALON_TIMEOUT_SEC", "10"))

# Синхронізація звернень
FEEDBACK_SYNC_BATCH_SIZE = int(os.getenv("FEEDBACK_SYNC_BATCH_SIZE", "100"))
FEEDBACK_SYNC_MAX_ROWS = int(os.getenv("FEEDBACK_SYNC_MAX_ROWS", "500"))

# Розсилка
BROADCAST_BATCH_SIZE = int(os.getenv("BROADCAST_BATCH_SIZE", "50"))
BROADCAST_PAUSE_SEC = float(os.getenv("BROADCAST_PAUSE_SEC", "0.2"))

# ===============================================
# 8. SMTP НАЛАШТУВАННЯ ДЛЯ EMAIL
# ===============================================
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.ukr.net")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_TARGET_EMAIL = os.getenv("SMTP_TARGET_EMAIL", "omet@omr.gov.ua")
SMTP_LEGAL_EMAIL = os.getenv("SMTP_LEGAL_EMAIL", SMTP_TARGET_EMAIL)

# ===============================================
# 9. МОДУЛЬ ОРЕНДИ ТРАМВАЇВ ТА ТРОЛЕЙБУСІВ
# ===============================================
VALENTIN_ADMIN_ID = 830196453
# Поки RENTAL_PUBLIC_ENABLED = False, розділ оренди бачать лише дозволені користувачі
RENTAL_PUBLIC_ENABLED = os.getenv("RENTAL_PUBLIC_ENABLED", "False") == "True"
RENTAL_ALLOWED_USER_IDS = [
    VALENTIN_ADMIN_ID,
    7453894165,
]
_allowed_env = os.getenv("RENTAL_ALLOWED_USER_IDS", "")
if _allowed_env:
    for _uid in _allowed_env.split(","):
        _uid = _uid.strip()
        if _uid.isdigit():
            RENTAL_ALLOWED_USER_IDS.append(int(_uid))

# ID спільного службового чату 6 підрозділів КП (якщо 0 — картки дублюються Валентину в особисті для тестування)
RENTAL_STAFF_CHAT_ID = int(os.getenv("RENTAL_STAFF_CHAT_ID", "-1004341305179"))

# Рольова матриця підрозділів КП у службовому чаті
RENTAL_STAFF_ROLES = {
    "traffic_service": [VALENTIN_ADMIN_ID],
    "legal_dept": [VALENTIN_ADMIN_ID],
    "vuptap_dept": [VALENTIN_ADMIN_ID],
    "accounting_dept": [VALENTIN_ADMIN_ID],
    "depot_tram": [VALENTIN_ADMIN_ID],
    "depot_trolley": [VALENTIN_ADMIN_ID],
}

# Банківські та юридичні реквізити КП «ОМЕТ» для генерації Договору та Інвойсу IBAN (QR НБУ)
RENTAL_RECIPIENT_NAME = os.getenv("RENTAL_RECIPIENT_NAME", "КП «Одесміськелектротранс»")
RENTAL_IBAN_COMPANY_NAME = RENTAL_RECIPIENT_NAME
RENTAL_EDRPOU = os.getenv("RENTAL_EDRPOU", "03328497")
RENTAL_IBAN_EDRPOU = RENTAL_EDRPOU
RENTAL_IBAN_ACCOUNT = os.getenv("RENTAL_IBAN_ACCOUNT", "UA903281680000000026000122581")
RENTAL_IBAN_ACCOUNT_SECONDARY = os.getenv("RENTAL_IBAN_ACCOUNT_SECONDARY", "UA533204780000026009924421337")
RENTAL_BANK_NAME = os.getenv("RENTAL_BANK_NAME", "ПАТ «МТБ БАНК»")
RENTAL_BANK_MFO = os.getenv("RENTAL_BANK_MFO", "328168")
RENTAL_BANK_NAME_SECONDARY = os.getenv("RENTAL_BANK_NAME_SECONDARY", "АБ «УКРГАЗБАНК»")
RENTAL_BANK_MFO_SECONDARY = os.getenv("RENTAL_BANK_MFO_SECONDARY", "320478")
RENTAL_VAT_IPN = os.getenv("RENTAL_VAT_IPN", "033284915016")
RENTAL_VAT_CERTIFICATE = os.getenv("RENTAL_VAT_CERTIFICATE", "100266021")
RENTAL_COMPANY_PHONE = os.getenv("RENTAL_COMPANY_PHONE", "048 717 54 00")
RENTAL_IBAN_BANK_NAME = RENTAL_BANK_NAME
RENTAL_DIRECTOR_FULL_NAME = os.getenv("RENTAL_DIRECTOR_FULL_NAME", "Литовчук Микола Володимирович")
RENTAL_DIRECTOR_NAME = os.getenv("RENTAL_DIRECTOR_NAME", "Микола ЛИТОВЧУК")
RENTAL_IBAN_DIRECTOR_TITLE = "Директор КП «Одесміськелектротранс»"
RENTAL_IBAN_DIRECTOR_NAME = os.getenv("RENTAL_IBAN_DIRECTOR_NAME", "Микола ЛИТОВЧУК")
RENTAL_OFFICE_ADDRESS = os.getenv("RENTAL_OFFICE_ADDRESS", "вул. Водопровідна, 1, м. Одеса, 65007")
RENTAL_IBAN_COMPANY_ADDRESS = RENTAL_OFFICE_ADDRESS

# Офіційна затверджена тарифікація КП «ОМЕТ» (Діє з 01.01.2026 р.)
# Вартість 1 години роботи трамвайного вагона РЕТРО з ПДВ 20%: 4 337,94 грн (без ПДВ 3 614,95 грн, ПДВ 722,99 грн)
RENTAL_TARIFF_RETRO_HOUR_UAH = float(os.getenv("RENTAL_TARIFF_RETRO_HOUR_UAH", "4337.94"))
RENTAL_MIN_ORDER_MINUTES = int(os.getenv("RENTAL_MIN_ORDER_MINUTES", "60"))

# Допоміжні / зворотні тарифи для сумісності
RENTAL_TARIFF_RETRO_KM = float(os.getenv("RENTAL_TARIFF_RETRO_KM", "180.0"))
RENTAL_TARIFF_STANDARD_KM = float(os.getenv("RENTAL_TARIFF_STANDARD_KM", "145.0"))
RENTAL_TARIFF_TROLLEY_KM = float(os.getenv("RENTAL_TARIFF_TROLLEY_KM", "135.0"))
RENTAL_TARIFF_WAIT_MIN = float(os.getenv("RENTAL_TARIFF_WAIT_MIN", "15.0"))

RENTAL_TARIFF_RETRO_TRAM_KM = RENTAL_TARIFF_RETRO_KM
RENTAL_TARIFF_STANDARD_TRAM_KM = RENTAL_TARIFF_STANDARD_KM
RENTAL_TARIFF_TROLLEYBUS_KM = RENTAL_TARIFF_TROLLEY_KM
RENTAL_TARIFF_WAIT_MINUTE = RENTAL_TARIFF_WAIT_MIN

RENTAL_EXTRA_DECORATION_UAH = float(os.getenv("RENTAL_EXTRA_DECORATION_UAH", "800.0"))
RENTAL_EXTRA_MUSIC_UAH = float(os.getenv("RENTAL_EXTRA_MUSIC_UAH", "500.0"))
RENTAL_EXTRA_GUIDE_UAH = float(os.getenv("RENTAL_EXTRA_GUIDE_UAH", "600.0"))
RENTAL_PAPER_TIMEOUT_HOURS = int(os.getenv("RENTAL_PAPER_TIMEOUT_HOURS", "36"))
RENTAL_PAPER_LOCK_HOURS = RENTAL_PAPER_TIMEOUT_HOURS
RENTAL_MIN_DAYS_KEP = int(os.getenv("RENTAL_MIN_DAYS_KEP", "3"))
RENTAL_MIN_DAYS_PAPER = int(os.getenv("RENTAL_MIN_DAYS_PAPER", "4"))

# Іконки для джерел часу
TIME_SOURCE_ICONS = {
    "gps": "🛰️",
    "schedule": "🗓️",
    "interval": "⏳",
    "unknown": "❓"
}