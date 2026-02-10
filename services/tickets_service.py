# services/tickets_service.py
from datetime import datetime, timezone
from sqlalchemy import select, func
from database.db import AsyncSessionLocal, Feedback
from config.constants import SHEET_NAMES
from integrations.google_sheets.client import GoogleSheetsClient
from config.settings import GOOGLE_SHEETS_ID, FEEDBACK_SYNC_BATCH_SIZE, FEEDBACK_SYNC_MAX_ROWS
from utils.logger import logger
from utils.text_formatter import format_ticket_id
import asyncio
import datetime
import random
from typing import Optional
from zoneinfo import ZoneInfo


class TicketsService:
    def __init__(self):
        self.sheets_client = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        self._kyiv_tz = ZoneInfo("Europe/Kyiv")

    def _to_kyiv_time(self, dt_value):
        if not dt_value:
            return None
        if dt_value.tzinfo is None:
            dt_value = dt_value.replace(tzinfo=timezone.utc)
        return dt_value.astimezone(self._kyiv_tz)

    def _format_phone_for_sheet(self, phone_value: Optional[str]):
        if not phone_value:
            return ""
        phone_str = str(phone_value).strip()
        if not phone_str:
            return ""
        if phone_str.startswith("'"):
            return phone_str
        if phone_str.startswith("0") or phone_str.startswith("+"):
            return f"'{phone_str}'"
        return phone_str

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
        start_ts = datetime.datetime.now()
        async with AsyncSessionLocal() as session:
            # Отримуємо всі несинхронізовані записи
            result = await session.execute(select(Feedback).where(Feedback.status == "new"))
            feedbacks = result.scalars().all()

            if not feedbacks:
                return 0

            loop = asyncio.get_running_loop()
            rows_by_sheet = {}

            for item in feedbacks[:FEEDBACK_SYNC_MAX_ROWS]:
                # Визначаємо ключ для SHEET_NAMES
                category_key = f"{item.category}s"  # За замовчуванням (complaint -> complaints)

                # Виправляємо для Подяк (бо в базі вони записані кирилицею "Подяки")
                if item.category == 'Подяки':
                    category_key = 'thanks'
                elif item.category == 'Скарги':  # Про всяк випадок
                    category_key = 'complaints'
                elif item.category == 'Пропозиції':  # Про всяк випадок
                    category_key = 'suggestions'

                # Отримуємо назву листа (напр. "Подяки")
                sheet_name = SHEET_NAMES.get(category_key, "Інше")

                # Формуємо рядок (порядок полів має збігатися з шапкою вашої таблиці!)
                # Приклад для Скарги: Дата | ID | Статус | Пріоритет | Маршрут | Проблема | Борт | Ім'я | Телефон | Email
                created_at_kyiv = self._to_kyiv_time(item.created_at)
                created_at_str = (
                    created_at_kyiv.strftime("%d.%m.%Y %H:%M")
                    if created_at_kyiv
                    else ""
                )

                row = [
                    created_at_str,
                    item.ticket_id,
                    "🆕 Нова (БД)",
                    "БД",
                    item.route or "N/A",
                    item.text,
                    item.board_number or "N/A",
                    item.user_name,
                    self._format_phone_for_sheet(item.user_phone),
                    item.user_email or ""
                ]

                rows_by_sheet.setdefault(sheet_name, []).append((item, row))

            for sheet_name, items_rows in rows_by_sheet.items():
                for i in range(0, len(items_rows), FEEDBACK_SYNC_BATCH_SIZE):
                    batch = items_rows[i:i + FEEDBACK_SYNC_BATCH_SIZE]
                    rows = [r for _, r in batch]

                    success = False
                    for attempt in range(3):
                        success = await loop.run_in_executor(
                            None,
                            self.sheets_client.append_rows,
                            sheet_name,
                            rows
                        )
                        if success:
                            break
                        await asyncio.sleep(2 ** attempt)

                    if success:
                        for item, _ in batch:
                            item.status = "synced"
                            count += 1

            await session.commit()
            duration = (datetime.datetime.now() - start_ts).total_seconds()
            logger.info(f"✅ Sheets sync finished: {count} rows in {duration:.1f}s")
            return count

    def generate_ticket_id(self):
        """Генерує випадковий ID для подяки"""
        import random  # Краще винести наверх файлу, але буде працювати і тут
        return f"#THX-{random.randint(10000, 99999)}"

    async def get_feedback_stats(self):
        async with AsyncSessionLocal() as session:
            total = await session.scalar(select(func.count(Feedback.id)))
            new_count = await session.scalar(
                select(func.count(Feedback.id)).where(Feedback.status == "new")
            )
            synced_count = await session.scalar(
                select(func.count(Feedback.id)).where(Feedback.status == "synced")
            )
            result = await session.execute(
                select(Feedback.category, func.count(Feedback.id)).group_by(Feedback.category)
            )
            by_category = {row[0]: row[1] for row in result.all() if row[0]}

            return {
                "total": total or 0,
                "new": new_count or 0,
                "synced": synced_count or 0,
                "by_category": by_category,
            }

    async def register_gratitude(self, data: dict):
        """
        Формує та записує подяку в Google таблицю.
        """
        import datetime  # Краще винести наверх файлу

        # Викликаємо метод через self
        ticket_id = self.generate_ticket_id()
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        gratitude_type = "Конкретна" if data.get('is_specific') else "Загальна"
        transport_type = data.get('transport_type', '')

        # Формуємо рядок (Колонка I - це 9-та по черзі)
        row = [
            ticket_id,  # A
            timestamp,  # B
            gratitude_type,  # C
            data.get('message', ''),  # D
            data.get('user_name', ''),  # E
            data.get('vehicle_number', ''),  # F
            data.get('email', ''),  # G
            "Новий",  # H
            transport_type  # I
        ]

        # ТУТ ВАЖЛИВО: Використовуй self.sheet_client (або як у тебе називається змінна клієнта в класі)
        # Припускаю, що в __init__ ти робив self.gs = ... або self.repo = ...
        # Якщо в тебе є метод add_row, викликай його:
        # await self.gs.add_row("НазваТаблиці", row)

        # Для прикладу повертаємо просто ID
        return ticket_id