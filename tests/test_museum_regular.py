import asyncio
import json
import uuid
import datetime
import sys
import os

# Додаємо корінь проекту в python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.db import init_db, AsyncSessionLocal, MuseumBooking
from services.museum_service import MuseumService
from config.constants import MuseumLimits

museum_service = MuseumService()


async def run_museum_regular_tests():
    print("🧪 [TEST] Initializing database...")
    await init_db()

    test_date = f"TEST_DATE_{uuid.uuid4().hex[:6]}"
    test_phone = f"099{uuid.uuid4().int % 10000000:07d}"

    print(f"🧪 [TEST 1] Initial booking count for date {test_date} should be 0")
    count_0 = await museum_service.get_bookings_count(test_date)
    assert count_0 == 0, f"Expected 0, got {count_0}"
    print("   ✅ Count is 0")

    print(f"🧪 [TEST 2] Check duplicate phone check for non-existent booking")
    has_booking = await museum_service.has_existing_booking(test_date, test_phone)
    assert has_booking is False, "Expected False for non-existent booking"
    print("   ✅ Duplicate check returned False")

    print(f"🧪 [TEST 3] Create regular booking with {MuseumLimits.REGULAR_MAX_PER_BOOKING} participants (ПІБ only, без віку)")
    participants = [
        {"name": "Петренко Петро Петрович", "age": None},
        {"name": "Петренко Ганна Петрівна", "age": None},
        {"name": "Петренко Іван Петрович", "age": None},
        {"name": "Петренко Марія Петрівна", "age": None},
        {"name": "Петренко Олег Петрович", "age": None},
    ]
    assert len(participants) == MuseumLimits.REGULAR_MAX_PER_BOOKING
    parts_json = json.dumps(participants, ensure_ascii=False)

    success = await museum_service.create_booking(
        date=test_date,
        count=MuseumLimits.REGULAR_MAX_PER_BOOKING,
        name=participants[0]["name"],
        phone=test_phone,
        participants_details=parts_json
    )
    assert success is True, "Expected create_booking to succeed"
    print("   ✅ Booking created successfully")

    print(f"🧪 [TEST 4] Verify SUM(people_count) for date {test_date}")
    count_1 = await museum_service.get_bookings_count(test_date)
    assert count_1 == MuseumLimits.REGULAR_MAX_PER_BOOKING, f"Expected SUM to be {MuseumLimits.REGULAR_MAX_PER_BOOKING}, got {count_1}"
    print(f"   ✅ SUM(people_count) is {count_1}")

    print(f"🧪 [TEST 5] Add a second booking of {MuseumLimits.REGULAR_MAX_PER_BOOKING} people for date {test_date}")
    test_phone_2 = f"099{uuid.uuid4().int % 10000000:07d}"
    participants_2 = [{"name": "Сидоренко Ольга Олексіївна", "age": None}]
    success_2 = await museum_service.create_booking(
        date=test_date,
        count=MuseumLimits.REGULAR_MAX_PER_BOOKING,
        name="Сидоренко Ольга Олексіївна",
        phone=test_phone_2,
        participants_details=json.dumps(participants_2, ensure_ascii=False)
    )
    assert success_2 is True

    expected_total = MuseumLimits.REGULAR_MAX_PER_BOOKING * 2
    count_2 = await museum_service.get_bookings_count(test_date)
    assert count_2 == expected_total, f"Expected SUM to be {expected_total}, got {count_2}"
    print(f"   ✅ SUM(people_count) correctly updated to {count_2}")

    print(f"🧪 [TEST 6] Check duplicate phone restriction")
    has_booking_dup = await museum_service.has_existing_booking(test_date, test_phone)
    assert has_booking_dup is True, "Expected True for existing booking"
    print("   ✅ Duplicate check correctly returned True for registered phone")

    print(f"🧪 [TEST 7] Verify participant details string formatting (без віку)")
    recent = await museum_service.get_last_bookings(limit=5)
    matching = [row for row in recent if row[1] == test_date]
    assert len(matching) == 2, f"Expected 2 rows for test date, got {len(matching)}"
    matching_first = [row for row in matching if "Петренко" in row[3]][0]
    expected_str = "1) Петренко Петро Петрович; 2) Петренко Ганна Петрівна; 3) Петренко Іван Петрович; 4) Петренко Марія Петрівна; 5) Петренко Олег Петрович"
    assert matching_first[3] == expected_str, f"Unexpected format: {matching_first[3]}"
    print(f"   ✅ Participant details properly formatted (без віку): {matching_first[3]}")

    print(f"🧪 [TEST 8] Capacity guard: get_bookings_count reflects both bookings towards {MuseumLimits.REGULAR_MAX_TOTAL} cap")
    remaining = MuseumLimits.REGULAR_MAX_TOTAL - count_2
    assert remaining == MuseumLimits.REGULAR_MAX_TOTAL - expected_total
    print(f"   ✅ Remaining capacity computed correctly: {remaining}")

    print("\n🎉 ALL 8 UNIT TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(run_museum_regular_tests())
