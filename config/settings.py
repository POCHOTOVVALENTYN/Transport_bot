import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Основні
BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv("DEBUG", "False") == "True"

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# Google Sheets
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
CREDENTIALS_PATH = BASE_DIR / "integrations/google_sheets/credentials.json"

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./transport_bot.db")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = BASE_DIR / "logs" / "bot.log"

# Trapport routes
ROUTES = {
    "tram": [1, 3, 5, 7, 9, 10, 12, 14, 16],
    "trolleybus": [2, 4, 6, 8, 11, 13, 15],
}

# ===== IMAGES PATH =====
IMAGES_PATH = BASE_DIR / "assets" / "images"

# Зображення для квитків
TICKET_PASSES_IMAGE_1 = IMAGES_PATH / "passes_part_1.png"
TICKET_PASSES_IMAGE_2 = IMAGES_PATH / "passes_part_2.png"

# ===== DOCUMENTS PATH =====
DOCUMENTS_PATH = BASE_DIR / "documents"
RULES_PDF_PATH = DOCUMENTS_PATH / "rules_of_use.pdf"