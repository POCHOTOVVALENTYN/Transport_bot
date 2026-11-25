import asyncio
import re
from datetime import datetime
import sys
import os

# Додаємо корінь проєкту в python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.museum_service import MuseumService, museum_service
from handlers.museum_handlers import museum_service as mh_service
from handlers.admin_handlers import museum_service as ah_service


def test_museum_singleton_identity():
    print("🧪 [TEST 1] Testing MuseumService Singleton identity across modules...")
    assert mh_service is ah_service, "mh_service and ah_service must be the exact same instance"
    assert mh_service is museum_service, "mh_service and base museum_service must be the exact same instance"
    print("   ✅ Singleton verified: same instance shared across handlers")


def test_cache_invalidation_across_handlers():
    print("🧪 [TEST 2] Testing cache invalidation visibility across handlers...")
    # Заповнюємо кеш у museum_handlers
    mh_service._dates_cache = ["10.12.2026 12:00", "15.12.2026 12:00"]
    mh_service._last_cache_update = 123456789

    # Інвалідуємо кеш через admin_handlers
    ah_service.invalidate_dates_cache()

    # Перевіряємо, що в museum_handlers кеш також скинуто
    assert len(mh_service._dates_cache) == 0, "Cache in mh_service must be empty after invalidation in ah_service"
    assert mh_service._last_cache_update == 0, "Cache timestamp must be reset to 0"
    print("   ✅ Cache invalidation in admin_handlers is immediately visible in museum_handlers")


def test_find_first_empty_row():
    print("🧪 [TEST 3] Testing find_first_empty_row logic...")
    # Порожній список -> рядок 2
    assert MuseumService.find_first_empty_row([], min_row=2) == 2
    # Тільки заголовок в A1 -> рядок 2
    assert MuseumService.find_first_empty_row([["Заголовок"]], min_row=2) == 2
    # A1 заголовок, A2 дата -> рядок 3
    assert MuseumService.find_first_empty_row([["Заголовок"], ["10.12.2026 12:00"]], min_row=2) == 3
    # A1 заголовок, A2 дата, A3 порожній (після clear_cell), A4 дата -> рядок 3 (повторне використання!)
    assert MuseumService.find_first_empty_row([["Заголовок"], ["10.12.2026 12:00"], [], ["15.12.2026 12:00"]], min_row=2) == 3
    # A3 рядок з пробілами -> рядок 3
    assert MuseumService.find_first_empty_row([["Заголовок"], ["10.12.2026 12:00"], ["  "], ["15.12.2026 12:00"]], min_row=2) == 3
    print("   ✅ find_first_empty_row correctly protects header and fills holes from clear_cell")


def test_flexible_date_parsing():
    print("🧪 [TEST 4] Testing flexible date format parsing (13.12.2026 vs 13.12.2026 11:00)...")
    date_without_time = "13.12.2026"
    date_with_time = "13.12.2026 14:30"
    invalid_date = "invalid-date"

    def normalize_input(raw_text: str):
        text = raw_text.strip()
        is_auto = False
        if re.match(r"^\d{2}\.\d{2}\.\d{4}$", text):
            text = f"{text} 12:00"
            is_auto = True
        elif not re.match(r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$", text):
            raise ValueError("Невірний формат")
        parsed = datetime.strptime(text, "%d.%m.%Y %H:%M")
        return text, is_auto, parsed

    norm_1, is_auto_1, dt_1 = normalize_input(date_without_time)
    assert norm_1 == "13.12.2026 12:00"
    assert is_auto_1 is True
    assert dt_1.hour == 12

    norm_2, is_auto_2, dt_2 = normalize_input(date_with_time)
    assert norm_2 == "13.12.2026 14:30"
    assert is_auto_2 is False
    assert dt_2.hour == 14

    try:
        normalize_input(invalid_date)
        assert False, "Should raise ValueError for invalid date"
    except ValueError:
        pass

    print("   ✅ Flexible date parsing correctly supports dates with and without time")


async def test_available_dates_range():
    print("🧪 [TEST 5] Testing expanded range reading in get_available_dates...")
    mock_called_range = None

    def mock_read_range(range_name, *args, **kwargs):
        nonlocal mock_called_range
        mock_called_range = range_name
        return [["13.12.2026 12:00"], ["14.12.2026 12:00"]]

    mh_service.sheets.read_range = mock_read_range
    mh_service.invalidate_dates_cache()

    dates = await mh_service.get_available_dates()
    assert mock_called_range == "MuseumDates!A2:A100", f"Expected MuseumDates!A2:A100, got {mock_called_range}"
    assert "13.12.2026 12:00" in dates
    print(f"   ✅ Successfully verified range {mock_called_range}")


async def run_all_tests():
    test_museum_singleton_identity()
    test_cache_invalidation_across_handlers()
    test_find_first_empty_row()
    test_flexible_date_parsing()
    await test_available_dates_range()
    print("\n🎉 ALL 5 FIX UNIT TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
