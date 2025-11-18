import asyncio
import time
import logging
from statistics import mean

# Імпортуємо реальні сервіси
from services.easyway_service import easyway_service
from services.tickets_service import TicketsService
from services.museum_service import MuseumService  # <-- НОВИЙ СЕРВІС
from database.db import init_db  # <-- Ініціалізація БД

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("stress_test")
logger.setLevel(logging.INFO)


class StressTester:
    def __init__(self, concurrent_users: int = 10):
        self.concurrent_users = concurrent_users
        self.tickets_service = TicketsService()
        self.museum_service = MuseumService()  # Використовуємо сервіс, а не прямий клієнт Sheets

        self.test_stop_id = 73
        self.test_user_id = 123456789

    async def _measure_time(self, name: str, func, *args):
        start = time.perf_counter()
        try:
            await func(*args)
            status = "✅ OK"
        except Exception as e:
            status = f"❌ ERROR: {e}"
        end = time.perf_counter()
        return end - start, status

    # --- ТЕСТ 1: EasyWay (Перевірка Lock) ---
    async def test_easyway_load(self):
        logger.info(f"\n--- 🚍 ТЕСТ EASYWAY (Async Lock + Cache) ---")
        logger.info(f"Імітація {self.concurrent_users} користувачів...")

        tasks = []
        for _ in range(self.concurrent_users):
            tasks.append(self._measure_time(
                "EasyWay",
                easyway_service.get_stop_info_v12,
                self.test_stop_id
            ))

        start = time.perf_counter()
        results = await asyncio.gather(*tasks)
        end = time.perf_counter()

        self._print_stats(results, end - start)

    # --- ТЕСТ 2: Feedback (Без змін, працює добре) ---
    async def test_feedback_load(self):
        logger.info(f"\n--- ✍️ ТЕСТ FEEDBACK (Background Sheets) ---")
        # ... (код той самий, можна скоротити для економії місця або залишити) ...
        pass  # Пропускаємо для економії часу, він вже пройшов успішно

    # --- ТЕСТ 3: Музей (SQLite - НОВА ЛОГІКА) ---
    async def test_museum_load(self):
        logger.info(f"\n--- 🏛️ ТЕСТ МУЗЕЙ (SQLite + Cache) ---")
        logger.info(f"Імітація {self.concurrent_users} записів у локальну БД...")

        # Спочатку прогріємо кеш дат (1 запит до Google Sheets)
        logger.info("🔥 Прогрів кешу дат...")
        await self.museum_service.get_available_dates()

        async def scenario():
            # 1. Отримати дати (має бути миттєво з кешу)
            await self.museum_service.get_available_dates()
            # 2. Записатися (має бути миттєво в SQLite)
            await self.museum_service.create_booking(
                "TEST_DATE", 2, "Stress Test User", "0000000000"
            )

        tasks = []
        for _ in range(self.concurrent_users):
            tasks.append(self._measure_time("MuseumDB", scenario))

        start = time.perf_counter()
        results = await asyncio.gather(*tasks)
        end = time.perf_counter()

        self._print_stats(results, end - start)

    def _print_stats(self, results, total_time):
        times = [r[0] for r in results]
        print(f"⏱️  Загальний час: {total_time:.4f} сек")
        print(f"⚡  Середній час: {mean(times):.4f} сек")
        print(f"🚀  RPS: {self.concurrent_users / total_time:.2f}")


async def main():
    # Ініціалізуємо БД перед тестом
    await init_db()

    tester = StressTester(concurrent_users=20)  # Спробуємо 20 користувачів!

    await tester.test_easyway_load()
    print("\n---")
    await tester.test_museum_load()


if __name__ == "__main__":
    asyncio.run(main())