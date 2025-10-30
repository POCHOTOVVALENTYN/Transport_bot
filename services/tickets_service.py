from datetime import datetime
from integrations.google_sheets.client import GoogleSheetsClient
from config.settings import GOOGLE_SHEETS_ID
from config.constants import SHEET_NAMES, TicketStatus
from utils.logger import logger
from utils.text_formatter import format_ticket_id, get_status_emoji
import uuid


class TicketsService:
    """Сервіс для управління тікетами скарг"""

    def __init__(self):
        self.sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)

    async def create_complaint_ticket(
            self,
            telegram_id: int,
            complaint_data: dict
    ) -> dict:
        """
        Створення тікету скарги в Google Sheets

        complaint_data повинен містити:
        {
            "problem": "опис",
            "route": "5",
            "board_number": "1234",
            "incident_datetime": "28.10.2025 14:30",
            "user_name": "Іван Петренко",
            "user_phone": "+380501234567"
        }
        """
        try:
            # Генерація ID
            ticket_id = format_ticket_id()

            # Формування рядка для Google Sheets
            row_data = [
                datetime.now().strftime("%d.%m.%Y %H:%M"),  # Дата створення
                ticket_id,  # ID тікету
                get_status_emoji(TicketStatus.NEW),  # Статус
                "🟡 Середня",  # Пріоритет
                complaint_data.get("route", "N/A"),  # Маршрут
                complaint_data.get("problem", "")[:100],  # Перші 100 символів
                complaint_data.get("board_number", "N/A"),  # Борт
                complaint_data.get("user_name", ""),  # Імя
                complaint_data.get("user_phone", ""),  # Телефон
                "",  # Примітки (порожньо)
                ""  # Адмін (порожньо)
            ]

            # Додавання в Google Sheets
            success = self.sheets.append_row(
                sheet_name=SHEET_NAMES["complaints"],
                values=row_data
            )

            if success:
                logger.info(f"✅ Complaint ticket created: {ticket_id}")
                return {
                    "success": True,
                    "ticket_id": ticket_id,
                    "message": f"✅ Ваша скарга зареєстрована!\nНомер: {ticket_id}"
                }
            else:
                return {
                    "success": False,
                    "message": "❌ Помилка при збереженні скарги"
                }

        except Exception as e:
            logger.error(f"❌ Error creating ticket: {e}")
            return {
                "success": False,
                "message": "❌ Сталася помилка"
            }

    async def create_suggestion_ticket(
            self,
            telegram_id: int,
            text: str,
            contact_info: str = "N/A"
    ) -> dict:
        """Створення тікету пропозиції"""
        try:
            ticket_id = format_ticket_id()

            row_data = [
                datetime.now().strftime("%d.%m.%Y %H:%M"),
                ticket_id,
                "💡 Пропозиція",
                "🟢 Низька",
                "N/A",  # Маршрут
                text[:100],
                "N/A",  # Борт
                contact_info.split(',')[0].strip() if contact_info != "N/A" else "Анонімно",  # Імя
                contact_info if contact_info != "N/A" else "N/A",  # Телефон/Контакт
                "",
                ""
            ]

            success = self.sheets.append_row(
                sheet_name=SHEET_NAMES["suggestions"],
                values=row_data
            )

            if success:
                logger.info(f"✅ Suggestion ticket created: {ticket_id}")
                return {
                    "success": True,
                    "ticket_id": ticket_id,
                    "message": f"💡 Дякуємо! Ваша пропозиція зареєстрована.\nНомер: {ticket_id}"
                }
            else:
                return {
                    "success": False,
                    "message": "❌ Помилка при збереженні пропозиції"
                }

        except Exception as e:
            logger.error(f"❌ Error creating suggestion: {e}")
            return {"success": False, "message": "❌ Сталася помилка"}

    async def create_thanks_ticket(
            self,
            telegram_id: int,
            text: str,
            route: str = None,
            board_number: str = None
    ) -> dict:
        """Створення тікету подяки"""
        try:
            ticket_id = format_ticket_id()

            row_data = [
                datetime.now().strftime("%d.%m.%Y %H:%M"),
                ticket_id,
                "✅ Подяка",
                "🟢 Низька",
                route or "N/A",
                text[:100],
                board_number or "N/A",
                "Користувач",
                "N/A",
                "",
                ""
            ]

            success = self.sheets.append_row(
                sheet_name=SHEET_NAMES["thanks"],
                values=row_data
            )

            if success:
                return {
                    "success": True,
                    "ticket_id": ticket_id,
                    "message": f"❤️ Дякуємо за зворотний зв'язок!\nНомер: {ticket_id}"
                }
            else:
                return {"success": False, "message": "❌ Помилка"}

        except Exception as e:
            logger.error(f"❌ Error creating thanks: {e}")
            return {"success": False, "message": "❌ Сталася помилка"}