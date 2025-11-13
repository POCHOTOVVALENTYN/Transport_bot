import asyncio
import json
from services.easyway_service import easyway_service
from utils.logger import logger  # Використовуємо ваш логгер

# --- Налаштування для тестів ---

# Візьмемо координати з вашого останнього логу (біля вул. Європейської / Привозу)
TEST_LAT = 46.4698
TEST_LNG = 30.7371

# Візьмемо ID зупинки "вул. Європейська" з вашого логу
TEST_STOP_ID = "73"

# ID маршруту "Трамвай 5" (я взяв його з відповіді 'cities.GetRoutesList')
# Це ID маршруту, а не номер
TEST_ROUTE_ID_TRAM_5 = "113"


# --- Кінець Налаштувань ---

async def run_test(test_name: str, func, *args):
    """Допоміжна функція для запуску та гарного друку"""
    logger.info(f"--- 🚀 РОЗПОЧАТО ТЕСТ: {test_name} ---")
    try:
        data = await func(*args)
        # Використовуємо json.dumps для гарного форматування
        pretty_data = json.dumps(data, indent=2, ensure_ascii=False)
        print(pretty_data)

        if data.get("error"):
            logger.error(f"--- ❌ ТЕСТ '{test_name}' ПРОВАЛЕНО (див. 'error' вище) ---")
        else:
            logger.info(f"--- ✅ ТЕСТ '{test_name}' УСПІШНО ЗАВЕРШЕНО ---")

    except Exception as e:
        logger.error(f"--- ❌ КРИТИЧНА ПОМИЛКА в '{test_name}': {e} ---", exc_info=True)

    print("\n" + "=" * 50 + "\n")


async def main():
    logger.info("🏁 Початок повного тестування API EasyWay...")

    # ТЕСТ 1: Які у нас взагалі права?
    await run_test(
        "user.GetMyInfo (Наші права)",
        easyway_service.get_my_info
    )

    # ТЕСТ 2: Чи працює "ідеальна" функція? (Очікуємо 'Unimplemented')
    await run_test(
        "stops.GetStopsNearPointWithRoutes (План А)",
        easyway_service.get_stops_near_point_with_routes,
        TEST_LAT, TEST_LNG
    )

    # ТЕСТ 3: Чи повертає 'stops.GetStopInfo' блок <transports>? (Очікуємо, що ні)
    await run_test(
        f"stops.GetStopInfo (План Б, зупинка ID: {TEST_STOP_ID})",
        easyway_service.get_stop_arrivals,
        TEST_STOP_ID
    )

    # ТЕСТ 4: (План С, частина 1) Чи можемо ми знайти GPS транспорту на маршруті?
    await run_test(
        f"routes.GetRouteGPS (План С, Трамвай 5, ID: {TEST_ROUTE_ID_TRAM_5})",
        easyway_service.get_route_gps,
        TEST_ROUTE_ID_TRAM_5
    )

    # ТЕСТ 5: (План С, частина 2) Які маршрути API бачить біля нас?
    await run_test(
        f"routes.GetRoutesNearPoint (План С, перевірка локації)",
        easyway_service.get_routes_near_point,
        TEST_LAT, TEST_LNG
    )

    logger.info("🏁 Тестування API завершено.")


if __name__ == "__main__":
    # Потрібно встановити той самий event loop policy, що і в aiohttp
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy() if "win" in str(
        asyncio.get_event_loop_policy()).lower() else asyncio.DefaultEventLoopPolicy())
    asyncio.run(main())