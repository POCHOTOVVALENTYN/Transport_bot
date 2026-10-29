import asyncio
import json
import uuid
import sys
import os

# Додаємо корінь проєкту в python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import delete
from database.db import init_db, AsyncSessionLocal, MuseumDateCapacity, MuseumBooking, MuseumHolidayBooking
from services.museum_service import MuseumService
from config.constants import MuseumLimits

museum_service = MuseumService()


async def _noop_sync(*args, **kwargs):
    return None


museum_service._sync_to_sheets_task = _noop_sync
museum_service._sync_holiday_to_sheets_task = _noop_sync


async def run_museum_capacity_tests():
    print("🧪 [TEST] Initializing database...")
    await init_db()

    test_regular_date = f"TEST_REG_DATE_{uuid.uuid4().hex[:6]}"
    test_holiday_date = f"TEST_HOL_DATE_{uuid.uuid4().hex[:6]}"

    try:
        # TEST 1: Fallback to default limits when no custom capacity is configured
        print("🧪 [TEST 1] Fallback to default capacity for unconfigured dates")
        cap_reg_default = await museum_service.get_date_max_capacity(test_regular_date, excursion_type="regular")
        assert cap_reg_default == MuseumLimits.REGULAR_MAX_TOTAL, f"Expected {MuseumLimits.REGULAR_MAX_TOTAL}, got {cap_reg_default}"
        print(f"   ✅ Regular default capacity is {cap_reg_default}")

        cap_hol_default = await museum_service.get_date_max_capacity(test_holiday_date, excursion_type="holiday")
        assert cap_hol_default == MuseumLimits.HOLIDAY_MAX_TOTAL, f"Expected {MuseumLimits.HOLIDAY_MAX_TOTAL}, got {cap_hol_default}"
        print(f"   ✅ Holiday default capacity is {cap_hol_default}")

        # TEST 2: Set custom capacity for regular date
        print("🧪 [TEST 2] Set custom capacity for regular date (25 seats)")
        saved_reg = await museum_service.set_date_max_capacity(test_regular_date, 25, excursion_type="regular")
        assert saved_reg is True, "Expected set_date_max_capacity to return True"
        cap_reg_custom = await museum_service.get_date_max_capacity(test_regular_date, excursion_type="regular")
        assert cap_reg_custom == 25, f"Expected 25, got {cap_reg_custom}"
        print(f"   ✅ Custom regular capacity stored and read: {cap_reg_custom}")

        # TEST 3: Set custom capacity for holiday date
        print("🧪 [TEST 3] Set custom capacity for holiday date (15 seats)")
        saved_hol = await museum_service.set_date_max_capacity(test_holiday_date, 15, excursion_type="holiday")
        assert saved_hol is True, "Expected set_date_max_capacity to return True"
        cap_hol_custom = await museum_service.get_date_max_capacity(test_holiday_date, excursion_type="holiday")
        assert cap_hol_custom == 15, f"Expected 15, got {cap_hol_custom}"
        print(f"   ✅ Custom holiday capacity stored and read: {cap_hol_custom}")

        # TEST 4: Update custom capacity for an existing date
        print("🧪 [TEST 4] Update custom capacity for existing regular date (25 -> 35 seats)")
        updated = await museum_service.set_date_max_capacity(test_regular_date, 35, excursion_type="regular")
        assert updated is True
        cap_reg_updated = await museum_service.get_date_max_capacity(test_regular_date, excursion_type="regular")
        assert cap_reg_updated == 35, f"Expected 35, got {cap_reg_updated}"
        print(f"   ✅ Updated capacity successfully verified: {cap_reg_updated}")

        # TEST 5: Booking availability calculation with dynamic capacity
        print("🧪 [TEST 5] Dynamic capacity booking availability check")
        test_phone = f"099{uuid.uuid4().int % 10000000:07d}"
        participants = [
            {"name": "Іваненко Іван Іванович", "age": None},
            {"name": "Іваненко Марія Іванівна", "age": None},
        ]
        created = await museum_service.create_booking(
            date=test_regular_date,
            count=2,
            name="Іваненко Іван Іванович",
            phone=test_phone,
            participants_details=json.dumps(participants, ensure_ascii=False)
        )
        assert created is True
        booked_count = await museum_service.get_bookings_count(test_regular_date)
        assert booked_count == 2
        remaining = cap_reg_updated - booked_count
        assert remaining == 33, f"Expected remaining 33, got {remaining}"
        print(f"   ✅ Booked {booked_count} out of {cap_reg_updated}, remaining {remaining} seats")

        # TEST 6: Remove date capacity and verify fallback to default
        print("🧪 [TEST 6] Remove date capacity and verify fallback back to default")
        removed = await museum_service.remove_date_capacity(test_regular_date, excursion_type="regular")
        assert removed is True
        cap_after_removal = await museum_service.get_date_max_capacity(test_regular_date, excursion_type="regular")
        assert cap_after_removal == MuseumLimits.REGULAR_MAX_TOTAL, f"Expected fallback to {MuseumLimits.REGULAR_MAX_TOTAL}, got {cap_after_removal}"
        print(f"   ✅ Successfully reverted to default limit {cap_after_removal} after removal")

        print("\n🎉 ALL 6 CAPACITY UNIT TESTS PASSED SUCCESSFULLY!")

    finally:
        # Cleanup
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(MuseumDateCapacity).where(
                    MuseumDateCapacity.excursion_date.in_([test_regular_date, test_holiday_date])
                )
            )
            await session.execute(
                delete(MuseumBooking).where(
                    MuseumBooking.excursion_date == test_regular_date
                )
            )
            await session.execute(
                delete(MuseumHolidayBooking).where(
                    MuseumHolidayBooking.excursion_date == test_holiday_date
                )
            )
            await session.commit()
        print("🧹 Cleaned up test database records")


if __name__ == "__main__":
    asyncio.run(run_museum_capacity_tests())
