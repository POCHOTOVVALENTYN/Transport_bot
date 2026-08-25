import asyncio
import json
import uuid
import datetime
import sys
import os

# Додаємо корінь проекту в python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.db import init_db, AsyncSessionLocal, MuseumHolidayBooking
from services.museum_service import MuseumService

museum_service = MuseumService()


async def run_museum_holiday_tests():
    print("🧪 [TEST] Initializing database...")
    await init_db()

    test_date = f"TEST_DATE_{uuid.uuid4().hex[:6]}"
    test_phone = f"099{uuid.uuid4().int % 10000000:07d}"

    print(f"🧪 [TEST 1] Initial booking count for date {test_date} should be 0")
    count_0 = await museum_service.get_holiday_bookings_count(test_date)
    assert count_0 == 0, f"Expected 0, got {count_0}"
    print("   ✅ Count is 0")

    print(f"🧪 [TEST 2] Check duplicate phone check for non-existent booking")
    has_booking = await museum_service.has_existing_holiday_booking(test_date, test_phone)
    assert has_booking is False, "Expected False for non-existent booking"
    print("   ✅ Duplicate check returned False")

    print(f"🧪 [TEST 3] Create holiday booking with 2 participants")
    participants = [
        {"name": "Петренко Петро Петрович", "age": 35},
        {"name": "Петренко Ганна Петрівна", "age": 8}
    ]
    parts_json = json.dumps(participants, ensure_ascii=False)

    success = await museum_service.create_holiday_booking(
        date=test_date,
        count=2,
        name="Петренко Петро Петрович",
        phone=test_phone,
        participants_details=parts_json
    )
    assert success is True, "Expected create_holiday_booking to succeed"
    print("   ✅ Booking created successfully")

    print(f"🧪 [TEST 4] Verify SUM(people_count) for date {test_date}")
    count_1 = await museum_service.get_holiday_bookings_count(test_date)
    assert count_1 == 2, f"Expected SUM to be 2, got {count_1}"
    print("   ✅ SUM(people_count) is 2")

    print(f"🧪 [TEST 5] Add a second booking of 2 people for date {test_date}")
    test_phone_2 = f"099{uuid.uuid4().int % 10000000:07d}"
    success_2 = await museum_service.create_holiday_booking(
        date=test_date,
        count=2,
        name="Сидоренко Ольга Олексіївна",
        phone=test_phone_2,
        participants_details=json.dumps([{"name": "Сидоренко Ольга", "age": 22}], ensure_ascii=False)
    )
    assert success_2 is True

    count_2 = await museum_service.get_holiday_bookings_count(test_date)
    assert count_2 == 4, f"Expected SUM to be 4 (2+2), got {count_2}"
    print("   ✅ SUM(people_count) correctly updated to 4")

    print(f"🧪 [TEST 6] Check duplicate phone restriction")
    has_booking_dup = await museum_service.has_existing_holiday_booking(test_date, test_phone)
    assert has_booking_dup is True, "Expected True for existing booking"
    print("   ✅ Duplicate check correctly returned True for registered phone")

    print(f"🧪 [TEST 7] Verify participant details string formatting")
    recent = await museum_service.get_last_holiday_bookings(limit=5)
    matching = [row for row in recent if row[1] == test_date]
    assert len(matching) == 2, f"Expected 2 rows for test date, got {len(matching)}"
    row_data = matching[-1]
    assert "1) Петренко Петро Петрович (35р.); 2) Петренко Ганна Петрівна (8р.)" in row_data[3], f"Unexpected format: {row_data[3]}"
    print(f"   ✅ Participant details properly formatted: {row_data[3]}")

    print("\n🎉 ALL 7 UNIT TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(run_museum_holiday_tests())
