
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

    def invalidate_dates_cache(self) -> None:
        """Скидає кеш дат після змін у Google Sheets (адмін: додавання/видалення)."""
        self._dates_cache = []
        self._last_cache_update = 0
        logger.info("🗑️ Museum dates cache invalidated")

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
        Повертає останні бронювання з локальної бази даних SQLite.
        Повертає «сирі» дані у вигляді списку списків для сумісності з попереднім кодом, включно з заголовком.
        """
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(MuseumBooking).order_by(MuseumBooking.created_at.desc()).limit(limit)
                )
                bookings = result.scalars().all()

                formatted_data = [["Дата реєстрації", "Дата екскурсії", "Кількість", "ПІБ", "Телефон"]]
                
                for b in bookings:
                    reg_date = b.created_at.strftime("%d.%m.%Y %H:%M") if b.created_at else "N/A"
                    formatted_data.append([
                        reg_date,
                        b.excursion_date,
                        str(b.people_count),
                        b.user_name,
                        b.user_phone
                    ])
                    
                logger.info(f"✅ Museum bookings: loaded {len(bookings)} rows from SQLite")
                return formatted_data
        except Exception as e:
            logger.error(f"❌ Error getting bookings from DB: {e}")
            return [["Дата реєстрації", "Дата екскурсії", "Кількість", "ПІБ", "Телефон"]]

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
                await session.refresh(booking)
                logger.info(f"✅ Booking saved to SQLite: {name}, {date}")

                # Запускаємо фонову задачу для відправки в Sheets
                asyncio.create_task(self._sync_to_sheets_task(booking.id))

                return True
        except Exception as e:
            logger.error(f"❌ Failed to save booking to DB: {e}")
            return False

    async def _sync_to_sheets_task(self, booking_id: int):
        """Фонова задача для синхронізації 1 запису в Google Sheets"""
        try:
            from datetime import datetime
            import asyncio
            
            async with AsyncSessionLocal() as session:
                booking = await session.get(MuseumBooking, booking_id)
                if not booking or booking.status == "synced":
                    return

                reg_date = booking.created_at.strftime("%d.%m.%Y %H:%M") if booking.created_at else ""
                row = [
                    reg_date,
                    booking.excursion_date,
                    str(booking.people_count),
                    booking.user_name,
                    booking.user_phone
                ]

                # Відправляємо в Google Sheets
                loop = asyncio.get_running_loop()
                success = await loop.run_in_executor(
                    None,
                    self.sheets.append_row,
                    "MuseumBookings",
                    row
                )

                if success:
                    booking.status = "synced"
                    await session.commit()
                    logger.info(f"✅ Sync to Sheets successful for booking ID {booking_id}")
        except Exception as e:
            logger.error(f"❌ Background sync failed: {e}")

    async def sync_unsynced_bookings(self):
        """
        Цю функцію можна викликати окремо (напр. адмін-командою),
        щоб вивантажити всі нові записи з БД в Google Sheets.
        """
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(MuseumBooking).where(MuseumBooking.status == "new")
                )
                bookings = result.scalars().all()
                if not bookings: return
                
                rows = []
                for b in bookings:
                    reg_date = b.created_at.strftime("%d.%m.%Y %H:%M") if b.created_at else ""
                    rows.append([reg_date, b.excursion_date, str(b.people_count), b.user_name, b.user_phone])
                
                # Відправляємо всі пакетом
                loop = asyncio.get_running_loop()
                success = await loop.run_in_executor(
                    None,
                    self.sheets.append_rows,
                    "MuseumBookings",
                    rows
                )
                
                if success:
                    for b in bookings:
                        b.status = "synced"
                    await session.commit()
                    logger.info(f"✅ Synced {len(rows)} past museum bookings to Google Sheets")
                    
        except Exception as e:
            logger.error(f"❌ Failed to sync past bookings: {e}")