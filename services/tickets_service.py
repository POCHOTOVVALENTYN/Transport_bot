from datetime import datetime
import asyncio
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
        """Створення тікету скарги в Google Sheets (Асинхронно)"""
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
                complaint_data.get("problem", ""),  # повний опис
                complaint_data.get("board_number", "N/A"),  # Борт
                complaint_data.get("user_name", ""),  # Імя
                complaint_data.get("user_phone", ""),  # Телефон
                complaint_data.get("user_email", "N/A"), # J
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
            suggestion_data: dict
    ) -> dict:
        """Створення тікету пропозиції (Оновлено)"""
        try:
            ticket_id = format_ticket_id()
            text = suggestion_data.get("text", "")
            user_name = suggestion_data.get("user_name", "Анонімно")
            user_phone = suggestion_data.get("user_phone", "N/A")

            row_data = [
                datetime.now().strftime("%d.%m.%Y %H:%M"),
                ticket_id,
                "💡 Пропозиція",
                "🟢 Низька",
                "N/A",
                text[:100],
                "N/A",
                user_name,
                user_phone,
                suggestion_data.get("user_email", "N/A")
            ]

            # === АСИНХРОННИЙ ВИКЛИК ===
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(
                None,
                self.sheets.append_row,
                SHEET_NAMES["suggestions"],
                row_data
            )

            if success:
                logger.info(f"✅ Suggestion ticket created: {ticket_id}")
                return {
                    "success": True,
                    "ticket_id": ticket_id,
                    "message": f"💡 Дякуємо! Ваша пропозиція зареєстрована.\nНомер: {ticket_id}"
                }
            else:
                return {"success": False, "message": "❌ Помилка при збереженні пропозиції"}

        except Exception as e:
            logger.error(f"❌ Error creating suggestion: {e}")
            return {"success": False, "message": "❌ Сталася помилка"}

    async def create_thanks_ticket(
            self,
            telegram_id: int,
            thanks_data: dict
    ) -> dict:
        """Створення тікету подяки (Асинхронно)"""
        try:
            ticket_id = format_ticket_id()

            row_data = [
                datetime.now().strftime("%d.%m.%Y %H:%M"),
                ticket_id,
                "✅ Подяка",
                "🟢 Низька",
                thanks_data.get("route") or "N/A",
                thanks_data.get("text", "")[:100],
                thanks_data.get("board_number") or "N/A",
                thanks_data.get("user_name", "Анонім"),
                "N/A",
                "",
                ""
            ]

            # === АСИНХРОННИЙ ВИКЛИК ===
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(
                None,
                self.sheets.append_row,
                SHEET_NAMES["thanks"],
                row_data
            )

            if success:
                return {
                    "success": True,
                    "ticket_id": ticket_id,
                    "message": f"❤️ Дякуємо! Вашу подяку зареєстровано.\nНомер: {ticket_id}"
                }
            else:
                return {"success": False, "message": "❌ Помилка"}

        except Exception as e:
            logger.error(f"❌ Error creating thanks: {e}")
            return {"success": False, "message": "❌ Сталася помилка"}