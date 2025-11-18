# services/tickets_service.py
from datetime import datetime
from sqlalchemy import select, func
from database.db import AsyncSessionLocal, Feedback
from config.constants import SHEET_NAMES
from integrations.google_sheets.client import GoogleSheetsClient
from config.settings import GOOGLE_SHEETS_ID
from utils.logger import logger
from utils.text_formatter import format_ticket_id
import asyncio


class TicketsService:
    def __init__(self):
        self.sheets_client = GoogleSheetsClient(GOOGLE_SHEETS_ID)

    async def _save_to_db(self, data: dict):
        """Універсальний метод збереження в БД"""
        try:
            async with AsyncSessionLocal() as session:
                feedback = Feedback(**data)
                session.add(feedback)
                await session.commit()
                return True
        except Exception as e:
            logger.error(f"❌ DB Save Error: {e}")
            return False

    async def create_complaint_ticket(self, telegram_id: int, complaint_data: dict) -> dict:
        ticket_id = format_ticket_id()

        # Готуємо об'єкт для БД
        db_data = {
            "ticket_id": ticket_id,
            "category": "complaint",
            "user_id": telegram_id,
            "text": complaint_data.get("problem"),
            "route": complaint_data.get("route"),
            "board_number": complaint_data.get("board_number"),
            "user_name": complaint_data.get("user_name"),
            "user_phone": complaint_data.get("user_phone"),
            "user_email": complaint_data.get("user_email"),
            "status": "new"
        }

        if await self._save_to_db(db_data):
            return {"success": True, "ticket_id": ticket_id, "message": f"✅ Скарга прийнята (ID: {ticket_id})"}
        return {"success": False, "message": "❌ Помилка бази даних"}

    # ... (Аналогічно оновіть create_suggestion_ticket та create_thanks_ticket, змінюючи лише category) ...

    async def create_suggestion_ticket(self, telegram_id: int, suggestion_data: dict) -> dict:
        ticket_id = format_ticket_id()
        db_data = {
            "ticket_id": ticket_id,
            "category": "suggestion",
            "user_id": telegram_id,
            "text": suggestion_data.get("text"),
            "user_name": suggestion_data.get("user_name"),
            "user_phone": suggestion_data.get("user_phone"),
            "user_email": suggestion_data.get("user_email"),
            "status": "new"
        }
        if await self._save_to_db(db_data):
            return {"success": True, "ticket_id": ticket_id, "message": f"💡 Пропозиція прийнята (ID: {ticket_id})"}
        return {"success": False, "message": "❌ Помилка"}

    async def create_thanks_ticket(self, telegram_id: int, thanks_data: dict) -> dict:
        ticket_id = format_ticket_id()
        db_data = {
            "ticket_id": ticket_id,
            "category": "thanks",
            "user_id": telegram_id,
            "text": thanks_data.get("text"),
            "route": thanks_data.get("route"),
            "board_number": thanks_data.get("board_number"),
            "user_name": thanks_data.get("user_name"),
            "status": "new"
        }
        if await self._save_to_db(db_data):
            return {"success": True, "ticket_id": ticket_id, "message": f"❤️ Подяка прийнята (ID: {ticket_id})"}
        return {"success": False, "message": "❌ Помилка"}

    # --- СИНХРОНІЗАЦІЯ (Для Адмінки) ---
    async def sync_new_feedbacks_to_sheets(self):
        """Читає всі 'new' записи з БД і вантажить в Google Sheets"""
        count = 0
        async with AsyncSessionLocal() as session:
            # Отримуємо всі несинхронізовані записи
            result = await session.execute(select(Feedback).where(Feedback.status == "new"))
            feedbacks = result.scalars().all()

            if not feedbacks:
                return 0

            loop = asyncio.get_running_loop()

            for item in feedbacks:
                # Визначаємо лист в залежності від категорії
                sheet_name = SHEET_NAMES.get(f"{item.category}s", "Інше")  # complaints -> Скарги

                # Формуємо рядок (порядок полів має збігатися з шапкою вашої таблиці!)
                # Приклад для Скарги: Дата | ID | Статус | Пріоритет | Маршрут | Проблема | Борт | Ім'я | Телефон | Email
                row = [
                    item.created_at.strftime("%d.%m.%Y %H:%M"),
                    item.ticket_id,
                    "🆕 Нова (БД)",
                    "БД",
                    item.route or "N/A",
                    item.text,
                    item.board_number or "N/A",
                    item.user_name,
                    item.user_phone,
                    item.user_email or ""
                ]

                # Відправляємо в Sheets (в окремому потоці)
                success = await loop.run_in_executor(
                    None,
                    self.sheets_client.append_row,
                    sheet_name,
                    row
                )

                if success:
                    item.status = "synced"
                    count += 1

            await session.commit()
            return count