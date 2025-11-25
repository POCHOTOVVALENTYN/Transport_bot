import os
import logging
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from config.settings import GOOGLE_SHEETS_CREDENTIALS_FILE, GOOGLE_SHEET_ID

logger = logging.getLogger(__name__)


class GoogleSheetsClient:
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    def __init__(self):
        self.creds = None
        self.service = None
        self.spreadsheet_id = GOOGLE_SHEET_ID
        self._authenticate()

    def _authenticate(self):
        if os.path.exists(GOOGLE_SHEETS_CREDENTIALS_FILE):
            self.creds = Credentials.from_service_account_file(
                GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=self.SCOPES)
            self.service = build('sheets', 'v4', credentials=self.creds)
            logger.info("✅ Google Sheets authenticated")
        else:
            logger.error(f"❌ Credentials file not found: {GOOGLE_SHEETS_CREDENTIALS_FILE}")

    def append_row(self, sheet_name: str, values: list):
        """
        Додає рядок у вказаний аркуш.
        Автоматично додає лапки до назви аркуша, щоб уникнути помилок з кирилицею.
        """
        if not self.service:
            logger.error("❌ Google Sheets service not initialized")
            return False

        try:
            # ВИПРАВЛЕННЯ: Безпечне форматування range з лапками для кирилиці
            # Якщо назва вже має лапки, не додаємо їх, інакше додаємо
            safe_sheet_name = sheet_name
            if " " in sheet_name or not sheet_name.isascii():
                if not sheet_name.startswith("'"):
                    safe_sheet_name = f"'{sheet_name}'"

            range_name = f"{safe_sheet_name}!A1"

            body = {
                'values': [values]
            }

            result = self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",  # Краще ніж RAW, бо форматує дати/числа
                body=body
            ).execute()

            logger.info(f"✅ Row appended to {sheet_name}")
            return True

        except Exception as e:
            # Детальна діагностика помилки
            error_msg = str(e)
            if "Unable to parse range" in error_msg:
                logger.error(
                    f"❌ Google Sheets Critical Error: Вкладка '{sheet_name}' не знайдена в таблиці! Створіть її.")
            else:
                logger.error(f"❌ Google Sheets error: {e}")
            return False