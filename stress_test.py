import asyncio
import time
import logging
import random
from statistics import mean

# Імпортуємо ваші сервіси
from services.easyway_service import easyway_service
from services.tickets_service import TicketsService
from integrations.google_sheets.client import GoogleSheetsClient
from config.settings import GOOGLE_SHEETS_ID

# Налаштування логування (тільки помилки та критичні повідомлення)
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("stress_test")
logger.setLevel(logging.INFO)


class StressTester:
    def __init__(self, concurrent_users: int = 10):
        self.concurrent_users = concurrent_users
        self.tickets_service = TicketsService()
        self.sheets_client = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        # Тестові дані
        self.test_stop_id = 73  # ID зупинки (напр. "вул. Європейська")
        self.test_user_id = 123456789

    async def _measure_time(self, name: str, func, *args):
        """Вимірює час виконання функції"""
        start = time.perf_counter()
        try:
            await func(*args)
            status = "✅ OK"
        except Exception as e:
            status = f"❌ ERROR: {e}"
        end = time.perf_counter()
        return end - start, status

    # --- ТЕСТ 1: EasyWay (Пошук інклюзивного транспорту) ---
    async def test_easyway_load(self):
        logger.info(f"\n--- 🚍 ТЕСТ EASYWAY (Кешування + API) ---")
        logger.info(
            f"Імітація {self.concurrent_users} користувачів, що одночасно запитують зупинку ID {self.test_stop_id}...")

        tasks = []
        for _ in range(self.concurrent_users):
            tasks.append(self._measure_time(
                "EasyWay",
                easyway_service.get_stop_info_v12,
                self.test_stop_id
            ))

        start_global = time.perf_counter()
        results = await asyncio.gather(*tasks)
        end_global = time.perf_counter()

        self._print_stats(results, end_global - start_global)

    # --- ТЕСТ 2: Зворотній зв'язок (Запис в Google Sheets) ---
    async def test_feedback_load(self):
        logger.info(f"\n--- ✍️ ТЕСТ FEEDBACK (Запис скарг в Google Sheets) ---")
        logger.info(f"Імітація {self.concurrent_users} користувачів, що одночасно відправляють скарги...")

        dummy_data = {
            "problem": "STRESS TEST COMPLAINT",
            "route": "TEST",
            "board_number": "0000",
            "user_name": "Test User",
            "user_phone": "0000000000"
        }

        tasks = []
        for _ in range(self.concurrent_users):
            tasks.append(self._measure_time(
                "Feedback",
                self.tickets_service.create_complaint_ticket,
                self.test_user_id,
                dummy_data
            ))

        start_global = time.perf_counter()
        results = await asyncio.gather(*tasks)
        end_global = time.perf_counter()

        self._print_stats(results, end_global - start_global)

    # --- ТЕСТ 3: Музей (Читання + Запис) ---
    async def _museum_scenario(self):
        # Емуляція повного циклу: користувач відкрив дати -> користувач записався
        # 1. Читання дат
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.sheets_client.read_range, "MuseumDates!A1:A10")
        # 2. Запис бронювання
        await loop.run_in_executor(
            None,
            self.sheets_client.append_row,
            "MuseumBookings",
            ["TEST_DATE", "TEST_DATE", "1", "Test User", "000"]
        )

    async def test_museum_load(self):
        logger.info(f"\n--- 🏛️ ТЕСТ МУЗЕЙ (Читання та запис Sheets) ---")
        logger.info(f"Імітація {self.concurrent_users} користувачів, що одночасно бронюють екскурсію...")

        tasks = []
        for _ in range(self.concurrent_users):
            tasks.append(self._measure_time("Museum", self._museum_scenario))

        start_global = time.perf_counter()
        results = await asyncio.gather(*tasks)
        end_global = time.perf_counter()

        self._print_stats(results, end_global - start_global)

    def _print_stats(self, results, total_time):
        times = [r[0] for r in results]
        errors = [r[1] for r in results if "ERROR" in r[1]]

        print(f"⏱️  Загальний час: {total_time:.4f} сек")
        print(f"⚡  Середній час на запит: {mean(times):.4f} сек")
        print(f"🚀  Швидкість (RPS): {self.concurrent_users / total_time:.2f} запитів/сек")

        if errors:
            print(f"❌  ПОМИЛОК: {len(errors)}")
            print(f"    Остання помилка: {errors[-1]}")
        else:
            print(f"✅  Успішно: {len(results)}/{len(results)}")


async def main():
    print("🚀 ЗАПУСК СТРЕС-ТЕСТУ...")
    print("⚠️  Увага: Цей тест створює реальні записи в Google Sheets. Не забудьте їх потім видалити.")

    # Кількість "користувачів" (почніть з 5, потім 20, потім 50)
    USERS = 10
    tester = StressTester(concurrent_users=USERS)

    # 1. Тест EasyWay (має бути дуже швидким, якщо працює кеш)
    await tester.test_easyway_load()

    # Пауза, щоб не отримати бан від Google API
    print("\n⏸️  Пауза 2 сек перед наступним тестом...")
    time.sleep(2)

    # 2. Тест Скарг (перевірка асинхронності запису)
    await tester.test_feedback_load()

    print("\n⏸️  Пауза 2 сек перед наступним тестом...")
    time.sleep(2)

    # 3. Тест Музею (найважчий сценарій)
    await tester.test_museum_load()

    print("\n🏁 ТЕСТ ЗАВЕРШЕНО.")


if __name__ == "__main__":
    asyncio.run(main())