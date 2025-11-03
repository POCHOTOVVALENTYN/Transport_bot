from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from typing import List, Optional
from config.settings import CREDENTIALS_PATH
from utils.logger import logger


class GoogleSheetsClient:
    """Клієнт для взаємодії з Google Sheets API"""

    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    def __init__(self, spreadsheet_id: str):
        self.spreadsheet_id = spreadsheet_id
        self.service = self._authenticate()

    def _authenticate(self):
        """Аутентифікація з Google API"""
        try:
            credentials = Credentials.from_service_account_file(
                str(CREDENTIALS_PATH),
                scopes=self.SCOPES
            )
            service = build('sheets', 'v4', credentials=credentials)
            logger.info("✅ Google Sheets authenticated")
            return service
        except Exception as e:
            logger.error(f"❌ Authentication failed: {e}")
            raise

    def append_row(
            self,
            sheet_name: str,
            values: List,
            value_input_option: str = 'USER_ENTERED'
    ) -> bool:
        """Додавання рядка в таблицю"""
        try:
            body = {'values': [values]}

            result = self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=sheet_name,
                valueInputOption=value_input_option,
                body=body
            ).execute()

            logger.info(f"✅ Row appended to {sheet_name}")
            return True

        except HttpError as e:
            logger.error(f"❌ Google Sheets error: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Error appending row: {e}")
            return False

    def read_range(self, sheet_range: str) -> Optional[List[List[str]]]:
        """Читає діапазон комірок, наприклад 'Sheet1!A1:B2'."""
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=sheet_range
            ).execute()

            values = result.get('values', [])
            if values:
                logger.info(f"✅ Range {sheet_range} read successfully")
                return values
            else:
                logger.info(f"⚠️ No data found in range {sheet_range}")
                return None

        except HttpError as e:
            logger.error(f"❌ Google Sheets error reading range {sheet_range}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Error reading range: {e}")
            return None

    def clear_cell(self, sheet_name: str, cell: str) -> bool:
        """Очищує значення в комірці (для видалення дати адміном)"""
        try:
            # Нам потрібно отримати sheet_id для batchUpdate
            sheets_metadata = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()
            sheet_id = None
            for sheet in sheets_metadata.get('sheets', []):
                if sheet['properties']['title'] == sheet_name:
                    sheet_id = sheet['properties']['sheetId']
                    break

            if sheet_id is None:
                logger.error(f"❌ Sheet not found: {sheet_name} for clear_cell")
                return False

            # Розбір адреси комірки (напр. "A5")
            col_letter = ''.join([c for c in cell if c.isalpha()])
            row_num = int(''.join([c for c in cell if c.isdigit()]))
            col_index = ord(col_letter.upper()) - ord('A')
            row_index = row_num - 1  # 0-індексація

            requests = [{
                "updateCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_index,
                        "endRowIndex": row_index + 1,
                        "startColumnIndex": col_index,
                        "endColumnIndex": col_index + 1
                    },
                    "fields": "userEnteredValue"  # Очищуємо тільки значення
                }
            }]

            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={'requests': requests}
            ).execute()

            logger.info(f"✅ Cell {sheet_name}!{cell} cleared")
            return True

        except Exception as e:
            logger.error(f"❌ Error clearing cell {cell}: {e}")
            return False

    def update_cell(
            self,
            sheet_name: str,
            cell: str,
            value: str
    ) -> bool:
        """Оновлення значення в комірці"""
        try:
            body = {'values': [[value]]}

            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"{sheet_name}!{cell}",
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()

            logger.info(f"✅ Cell {cell} updated")
            return True

        except Exception as e:
            logger.error(f"❌ Error updating cell: {e}")
            return False

    def format_cell(
            self,
            sheet_name: str,
            cell: str,
            background_color: tuple = None,
            text_color: tuple = None,
            bold: bool = False
    ) -> bool:
        """Форматування комірки (RGB кортежі від 0 до 1)"""
        try:
            # Розбір адреси комірки
            col_letter = ''.join([c for c in cell if c.isalpha()])
            row_num = int(''.join([c for c in cell if c.isdigit()]))
            col_num = ord(col_letter.upper()) - ord('A')

            # Отримання sheet_id
            sheets_metadata = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()

            sheet_id = None
            for sheet in sheets_metadata.get('sheets', []):
                if sheet['properties']['title'] == sheet_name:
                    sheet_id = sheet['properties']['sheetId']
                    break

            if sheet_id is None:
                logger.error(f"❌ Sheet not found: {sheet_name}")
                return False

            # Формування запиту
            format_dict = {}

            if background_color:
                format_dict['backgroundColor'] = {
                    'red': background_color[0],
                    'green': background_color[1],
                    'blue': background_color[2]
                }

            if text_color or bold:
                format_dict['textFormat'] = {}
                if text_color:
                    format_dict['textFormat']['foregroundColor'] = {
                        'red': text_color[0],
                        'green': text_color[1],
                        'blue': text_color[2]
                    }
                if bold:
                    format_dict['textFormat']['bold'] = True

            requests = [{
                'updateCells': {
                    'range': {
                        'sheetId': sheet_id,
                        'rowIndex': row_num - 1,
                        'columnIndex': col_num,
                        'endRowIndex': row_num,
                        'endColumnIndex': col_num + 1
                    },
                    'rows': [{'values': [{'userEnteredFormat': format_dict}]}],
                    'fields': 'userEnteredFormat'
                }
            }]

            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={'requests': requests}
            ).execute()

            logger.info(f"✅ Cell {cell} formatted")
            return True

        except Exception as e:
            logger.error(f"❌ Error formatting cell: {e}")
            return False