import os
from typing import Optional
import logging
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from config.settings import GOOGLE_SHEETS_CREDENTIALS_FILE, GOOGLE_SHEET_ID

logger = logging.getLogger(__name__)


class GoogleSheetsClient:
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    def __init__(self, spreadsheet_id=None):
        """
        Ініціалізація клієнта.
        :param spreadsheet_id: (Опціонально) ID таблиці. Якщо не передано, береться з конфігу.
        """
        self.creds = None
        self.service = None
        # Якщо передали ID — беремо його, якщо ні — беремо з settings.py
        self.spreadsheet_id = spreadsheet_id or GOOGLE_SHEET_ID
        self._authenticate()

    def _authenticate(self):
        if os.path.exists(GOOGLE_SHEETS_CREDENTIALS_FILE):
            try:
                self.creds = Credentials.from_service_account_file(
                    GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=self.SCOPES)
                self.service = build('sheets', 'v4', credentials=self.creds)
                logger.info("✅ Google Sheets authenticated")
            except Exception as e:
                logger.error(f"❌ Auth Error: {e}")
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
            # Безпечне форматування range з лапками для кирилиці
            safe_sheet_name = sheet_name
            if " " in sheet_name or not sheet_name.isascii():
                if not sheet_name.startswith("'"):
                    safe_sheet_name = f"'{sheet_name}'"

            range_name = f"{safe_sheet_name}!A1"

            body = {
                'values': [values]
            }

            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()

            logger.info(f"✅ Row appended to {sheet_name}")
            return True

        except Exception as e:
            error_msg = str(e)
            if "Unable to parse range" in error_msg:
                logger.error(
                    f"❌ Google Sheets Critical Error: Вкладка '{sheet_name}' не знайдена в таблиці! Створіть її.")
            else:
                logger.error(f"❌ Google Sheets error: {e}")
            return False

    def read_range(self, range_name: Optional[str] = None, sheet_range: Optional[str] = None):
        """
        Читає діапазон клітинок з таблиці та повертає список списків значень.

        Параметри:
        - range_name: стандартний A1-діапазон (наприклад, \"MuseumDates!A1:A50\").
        - sheet_range: те саме, що range_name (залишено для зворотної сумісності з існуючими викликами).
        """
        if not self.service:
            logger.error("❌ Google Sheets service not initialized")
            return []

        # Підтримуємо обидва варіанти імені аргументу
        final_range = sheet_range or range_name
        if not final_range:
            logger.error("❌ Google Sheets read_range: не передано діапазон")
            return []

        try:
            result = (
                self.service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=self.spreadsheet_id,
                    range=final_range,
                )
                .execute()
            )
            values = result.get("values", [])
            logger.info(f"✅ Read {len(values)} rows from range {final_range}")
            return values
        except Exception as e:
            logger.error(f"❌ Google Sheets read_range error ({final_range}): {e}")
            return []

    def clear_cell(self, sheet_name: str, cell: str) -> bool:
        """
        Очищає одну клітинку (наприклад, A5) на вказаному аркуші.
        sheet_name — назва вкладки (\"MuseumDates\" тощо),
        cell — адреса клітинки у форматі A1 (\"A5\").
        """
        if not self.service:
            logger.error("❌ Google Sheets service not initialized")
            return False

    def append_rows(self, sheet_name: str, values: list):
        """
        Додає декілька рядків у вказаний аркуш.
        Автоматично додає лапки до назви аркуша, щоб уникнути помилок з кирилицею.
        """
        if not self.service:
            logger.error("❌ Google Sheets service not initialized")
            return False

        try:
            safe_sheet_name = sheet_name
            if " " in sheet_name or not sheet_name.isascii():
                if not sheet_name.startswith("'"):
                    safe_sheet_name = f"'{sheet_name}'"

            range_name = f"{safe_sheet_name}!A1"
            body = {'values': values}

            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()

            logger.info(f"✅ Rows appended to {sheet_name}: {len(values)}")
            return True

        except Exception as e:
            error_msg = str(e)
            if "Unable to parse range" in error_msg:
                logger.error(
                    f"❌ Google Sheets Critical Error: Вкладка '{sheet_name}' не знайдена в таблиці! Створіть її."
                )
            else:
                logger.error(f"❌ Google Sheets error: {e}")
            return False

        try:
            safe_sheet_name = sheet_name
            if " " in sheet_name or not sheet_name.isascii():
                if not sheet_name.startswith("'"):
                    safe_sheet_name = f"'{sheet_name}'"

            range_name = f"{safe_sheet_name}!{cell}"

            (
                self.service.spreadsheets()
                .values()
                .clear(
                    spreadsheetId=self.spreadsheet_id,
                    range=range_name,
                    body={},
                )
                .execute()
            )

            logger.info(f"✅ Cleared cell {range_name}")
            return True
        except Exception as e:
            logger.error(f"❌ Google Sheets clear_cell error ({sheet_name}!{cell}): {e}")
            return False