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
            suggestion_data: dict
    ) -> dict:
        """Створення тікету пропозиції (Оновлено)"""
        try:
            ticket_id = format_ticket_id()

            # Дані, які ми отримуємо
            text = suggestion_data.get("text", "")
            user_name = suggestion_data.get("user_name", "Анонімно")
            user_phone = suggestion_data.get("user_phone", "N/A")

            # Формування рядка згідно 9 колонок:
            # Дата | Номер | Тип | Пріоритет | Маршрут | Опис | Борт | ПІБ | Телефон
            row_data = [
                datetime.now().strftime("%d.%m.%Y %H:%M"),  # Дата реєстрації
                ticket_id,  # Номер пропозиції
                "💡 Пропозиція",  # Тип
                "🟢 Низька",  # Пріоритет
                "N/A",  # № Маршруту
                text[:100],  # Опис
                "N/A",  # Бортовий №
                user_name,  # П.І.Б.
                user_phone  # Телефон
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
            thanks_data: dict
    ) -> dict:
        """Створення тікету подяки"""
        try:
            ticket_id = format_ticket_id()

            row_data = [
                datetime.now().strftime("%d.%m.%Y %H:%M"),  # Дата
                ticket_id,  # ID
                "✅ Подяка",  # Статус
                "🟢 Низька",  # Пріоритет
                thanks_data.get("route") or "N/A",  # Маршрут
                thanks_data.get("text", "")[:100],  # Текст
                thanks_data.get("board_number") or "N/A",  # Борт
                thanks_data.get("user_name", "Анонім"),  # ІМ'Я
                "N/A",  # Телефон (не збираємо)
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
                    "message": f"❤️ Дякуємо! Вашу подяку зареєстровано.\nНомер: {ticket_id}"
                }
            else:
                return {"success": False, "message": "❌ Помилка"}

        except Exception as e:
            logger.error(f"❌ Error creating thanks: {e}")
            return {"success": False, "message": "❌ Сталася помилка"}