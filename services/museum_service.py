
from sqlalchemy import select
from database.db import AsyncSessionLocal, MuseumBooking
from integrations.google_sheets.client import GoogleSheetsClient

from utils.logger import logger
import asyncio
import time


class MuseumService:
    def __init__(self):
        self.sheets = GoogleSheetsClient()
        self._dates_cache = []
        self._last_cache_update = 0
        self._cache_ttl = 300  # Кеш живе 5 хвилин (300 сек)

    async def get_available_dates(self) -> list:
        """
        Отримує дати екскурсій.
        Спочатку дивиться в кеш. Якщо кеш старий -> читає з Google Sheets.
        """
        current_time = time.time()

        # Якщо кеш свіжий і не пустий - віддаємо його
        if self._dates_cache and (current_time - self._last_cache_update < self._cache_ttl):
            logger.info("💎 Museum dates: Cache HIT")
            return self._dates_cache

        logger.info("🔄 Museum dates: Updating from Google Sheets...")

        # Читаємо з Google Sheets (в окремому потоці, щоб не блокувати)
        loop = asyncio.get_running_loop()
        raw_dates = await loop.run_in_executor(
            None,
            self.sheets.read_range,
            "MuseumDates!A1:A50"
        )

        if raw_dates:
            # Оновлюємо кеш
            self._dates_cache = [row[0] for row in raw_dates if row]
            self._last_cache_update = current_time
            return self._dates_cache

        return []

    async def get_last_bookings(self, limit: int = 50) -> list:
        """
        Повертає останні бронювання з аркуша MuseumBookings.
        Повертає «сирі» дані з Google Sheets (список списків), включно з заголовком.
        """
        loop = asyncio.get_running_loop()
        range_name = f"MuseumBookings!A1:E{limit + 1}"  # +1 на рядок заголовків
        bookings_data = await loop.run_in_executor(
            None,
            self.sheets.read_range,
            range_name
        )
        if not bookings_data:
            logger.info("ℹ️ Museum bookings: no data returned from Google Sheets")
            return []
        logger.info(f"✅ Museum bookings: loaded {len(bookings_data)} rows from Google Sheets")
        return bookings_data

    async def create_booking(self, date: str, count: int, name: str, phone: str) -> bool:
        """
        Миттєво зберігає бронювання в локальну БД SQLite.
        """
        try:
            async with AsyncSessionLocal() as session:
                booking = MuseumBooking(
                    excursion_date=date,
                    people_count=count,
                    user_name=name,
                    user_phone=phone
                )
                session.add(booking)
                await session.commit()
                logger.info(f"✅ Booking saved to SQLite: {name}, {date}")

                # ЗА БАЖАННЯМ: Можна запустити фонову задачу для відправки в Sheets
                # asyncio.create_task(self._sync_to_sheets(booking))

                return True
        except Exception as e:
            logger.error(f"❌ Failed to save booking to DB: {e}")
            return False

    async def sync_unsynced_bookings(self):
        """
        Цю функцію можна викликати окремо (напр. адмін-командою),
        щоб вивантажити всі нові записи з БД в Google Sheets.
        """
        # Логіка вибірки з БД записів зі статусом 'new' і запис їх у Sheets
        pass