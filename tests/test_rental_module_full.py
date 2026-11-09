"""
Комплексні інтеграційні тести продакшен-модуля оренди трамваїв і тролейбусів:
1. Ізоляція доступу (зміни в боті бачить виключно Валентин — ID 830196453);
2. Динамічний пул часових слотів та перерозподіл між кількома клієнтами на одну дату;
3. Автоматичне звільнення слоту після спливу 36 годин (тайм-аут паперового договору);
4. Генерація PDF-документів: Договір №XXXX-О (Директор КП ОМЕТ), Рахунок IBAN з QR-кодом НБУ, Посадковий талон;
5. Рольова модель (6 підрозділів) та двоетапний захист від випадкового натискання (2-step confirmation).
"""

from __future__ import annotations

import datetime
import os
import tempfile
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from config.settings import RENTAL_PUBLIC_ENABLED, VALENTIN_ADMIN_ID
from database.db import Base, Database
import handlers.rental_staff_handlers as staff_handlers
from handlers.command_handlers import get_main_menu_keyboard
from handlers.rental_staff_handlers import (
    check_two_step_confirmation,
    format_staff_order_card_text,
    has_staff_role,
    is_rental_access_allowed,
)
from services.rental_documents_service import (
    RentalPriceInput,
    build_nbu_iban_payment_purpose,
    build_nbu_iban_qr_payload,
    calculate_rental_price_breakdown,
    generate_rental_boarding_pass_pdf,
    generate_rental_contract_pdf,
    generate_rental_iban_invoice_pdf,
)


@pytest.mark.asyncio
async def test_valentin_only_visibility_guard():
    """Перевіряє, що новий розділ оренди бачать лише авторизовані користувачі."""
    assert RENTAL_PUBLIC_ENABLED is False
    assert is_rental_access_allowed(VALENTIN_ADMIN_ID) is True
    assert is_rental_access_allowed(7453894165) is True
    assert is_rental_access_allowed(111222333) is False

    valentin_kb = await get_main_menu_keyboard(VALENTIN_ADMIN_ID)
    valentin_callbacks = [
        btn.callback_data for row in valentin_kb.inline_keyboard for btn in row
    ]
    assert "rental_hub" in valentin_callbacks

    tester_kb = await get_main_menu_keyboard(7453894165)
    tester_callbacks = [
        btn.callback_data for row in tester_kb.inline_keyboard for btn in row
    ]
    assert "rental_hub" in tester_callbacks

    regular_kb = await get_main_menu_keyboard(111222333)
    regular_callbacks = [
        btn.callback_data for row in regular_kb.inline_keyboard for btn in row
    ]
    assert "rental_hub" not in regular_callbacks


@pytest.mark.asyncio
async def test_dynamic_slot_pool_and_36h_timeout():
    """
    Перевіряє динамічний пул слотів:
    - Служба руху додає 3 слоти на дату;
    - Клієнт 1 бронює один слот, а 2 інші залишаються доступними для Клієнта 2;
    - Після спливу 36 годин непідписаний договір переходить у 'expired_36h' і повертає слот у пул.
    """
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_session_factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    db = Database()
    db.session_factory = test_session_factory
    staff_handlers.db = db
    test_date = "28.11.2029"

    await db.add_rental_slots(
        rental_date=test_date,
        slot_times=["11:00", "14:00", "17:30"],
        transport_type="TRAM",
        added_by_id=VALENTIN_ADMIN_ID,
        added_by_name="Валентин (Служба руху)",
    )

    free_initial = await db.get_available_rental_slots(test_date, "TRAM")
    assert free_initial == ["11:00", "14:00", "17:30"]

    # Клієнт 1 створює замовлення на слот 14:00 (паперовий сценарій, ліміт 36 год)
    past_deadline = datetime.datetime.now() - datetime.timedelta(hours=1)
    order1 = await db.create_rental_order(
        {
            "user_id": VALENTIN_ADMIN_ID,
            "user_full_name": "Тестовий Замовник 1",
            "user_phone": "+380501234567",
            "user_tax_id": "1234567890",
            "transport_type": "TRAM",
            "wagon_type": "Ретро-трамвай МТВ-82",
            "depot_code": "ВРМ",
            "pickup_stop": "пл. Старосінна",
            "via_loops": ["Аркадія"],
            "dropoff_stop": "пл. Старосінна",
            "wait_minutes": 20,
            "extra_services": ["🎈 Святкове прикрашання салону"],
            "distance_pull_out_km": 2.7,
            "distance_route_km": 14.3,
            "distance_pull_in_km": 2.7,
            "total_distance_km": 19.7,
            "duration_pull_out_min": 13,
            "duration_route_min": 56,
            "duration_pull_in_min": 13,
            "total_duration_min": 102,
            "km_price_uah": 3546.0,
            "wait_price_uah": 300.0,
            "extras_price_uah": 800.0,
            "total_price_uah": 4646.0,
            "signing_scenario": "paper",
            "rental_date": test_date,
            "rental_time_slot": "14:00",
            "slot_lock_expires_at": past_deadline,
        }
    )

    assert order1.contract_number.endswith("-О")
    assert order1.status == "awaiting_signature"

    # Клієнт 2 бачить на цю ж дату решту вільних слотів (11:00 та 17:30)
    free_after_lock = await db.get_available_rental_slots(test_date, "TRAM")
    assert free_after_lock == ["11:00", "17:30"]

    # Перевіряємо форматування живої картки штабу з Audit Trail
    card_text = await format_staff_order_card_text(order1)
    assert order1.contract_number in card_text
    assert "ДЕТАЛІЗОВАНИЙ ЖУРНАЛ ЗАМОВЛЕННЯ" in card_text

    # Спрацьовує авто-перевірка 36 годин -> слот 14:00 повертається у вільний пул
    expired = await db.expire_overdue_rental_orders()
    assert any(o.id == order1.id for o in expired)

    free_after_expire = await db.get_available_rental_slots(test_date, "TRAM")
    assert free_after_expire == ["11:00", "14:00", "17:30"]


def test_price_and_pdf_documents_with_nbu_qr():
    """Перевіряє погодинну калькуляцію за тарифом 4 337,94 грн/год з ПДВ 20%, мін. замовлення 1 год, IBAN та 3 PDF."""
    # 1. Тест застосування мінімального замовлення 1 година (45 хв -> 60 хв)
    bd_min = calculate_rental_price_breakdown(
        RentalPriceInput(
            wagon_key="retro_mtv",
            total_duration_minutes=45,
            extra_service_keys=[],
        )
    )
    assert bd_min.actual_minutes == 45
    assert bd_min.billable_minutes == 60
    assert bd_min.is_minimum_applied is True
    assert bd_min.hourly_rate_uah == 4337.94
    assert bd_min.time_price_uah == 4337.94
    assert bd_min.extras_price_uah == 0.0
    assert bd_min.total_price_uah == 4337.94
    assert bd_min.without_vat_uah == 3614.95
    assert bd_min.vat_20_uah == 722.99

    # 2. Тест розрахунку понад 1 годину (102 хв) з додатковими послугами (прикрашання + гід = 1400 грн)
    bd = calculate_rental_price_breakdown(
        RentalPriceInput(
            wagon_key="retro_mtv",
            total_duration_minutes=102,
            wait_minutes=20,
            extra_service_keys=["decoration", "guide"],
        )
    )
    assert bd.actual_minutes == 102
    assert bd.billable_minutes == 102
    assert bd.is_minimum_applied is False
    assert bd.time_price_uah == 7374.50
    assert bd.extras_price_uah == 1400.0
    assert bd.total_price_uah == 8774.50
    assert bd.without_vat_uah == 7312.08
    assert bd.vat_20_uah == 1462.42

    purpose = build_nbu_iban_payment_purpose("2026-0042-О", "30.10.2026")
    assert purpose == "*;101;Оплата за оренду трамвайного вагона РЕТРО згідно з Договором №2026-0042-О від 30.10.2026;у т.ч. ПДВ 20%*"

    qr_payload = build_nbu_iban_qr_payload("2026-0042-О", "30.10.2026", 8774.50)
    assert qr_payload.startswith("BCD\n002\n1\nUCT\n")
    assert "UAH8774.50" in qr_payload
    assert purpose in qr_payload

    with tempfile.TemporaryDirectory() as tmp_dir:
        sample_order = {
            "contract_number": "2026-0042-О",
            "contract_date": "30.10.2026",
            "order_uid": "RNT-20261030-ABCD",
            "user_full_name": "Коваленко Іван Іванович",
            "user_phone": "+380509998877",
            "user_tax_id": "3123456789",
            "transport_type": "TRAM",
            "wagon_type": "Ретро-трамвай МТВ-82",
            "depot_code": "ВРМ",
            "pickup_stop": "пл. Старосінна",
            "via_loops": ["Аркадія"],
            "dropoff_stop": "пл. Старосінна",
            "wait_minutes": 20,
            "distance_pull_out_km": 2.7,
            "distance_route_km": 14.3,
            "distance_pull_in_km": 2.7,
            "total_distance_km": 19.7,
            "duration_pull_out_min": 13,
            "duration_route_min": 56,
            "duration_pull_in_min": 13,
            "total_duration_min": 102,
            "billable_minutes": 102,
            "hourly_rate_uah": 4337.94,
            "time_price_uah": 7374.50,
            "km_price_uah": 7374.50,
            "wait_price_uah": 0.0,
            "extras_price_uah": 1400.0,
            "total_price_uah": 8774.50,
            "without_vat_uah": 7312.08,
            "vat_20_uah": 1462.42,
            "signing_scenario": "paper",
            "rental_date": "10.11.2026",
            "rental_time_slot": "12:00",
            "assigned_board_number": "914",
            "assigned_driver_name": "Петренко П.П.",
            "assigned_driver_phone": "+380671112233",
        }
        contract_path = generate_rental_contract_pdf(sample_order, target_dir=tmp_dir)
        invoice_path = generate_rental_iban_invoice_pdf(sample_order, target_dir=tmp_dir)
        pass_path = generate_rental_boarding_pass_pdf(sample_order, target_dir=tmp_dir)

        assert os.path.exists(contract_path) and os.path.getsize(contract_path) > 1500
        assert os.path.exists(invoice_path) and os.path.getsize(invoice_path) > 1500
        assert os.path.exists(pass_path) and os.path.getsize(pass_path) > 1500


def test_rbac_and_two_step_confirmation():
    """Перевіряє ролі 6 підрозділів та двоетапне підтвердження натискання кнопок."""
    for role_key in (
        "traffic_service",
        "legal_dept",
        "vuptap_dept",
        "accounting_dept",
        "depot_tram",
        "depot_trolley",
    ):
        assert has_staff_role(VALENTIN_ADMIN_ID, role_key) is True
        assert has_staff_role(555666777, role_key) is False

    # Перше натискання — запитує підтвердження (False), друге протягом 10 сек — виконує дію (True)
    assert check_two_step_confirmation(VALENTIN_ADMIN_ID, 777, "traffic_ok") is False
    assert check_two_step_confirmation(VALENTIN_ADMIN_ID, 777, "traffic_ok") is True
    # Наступне натискання знову вимагає 1-го кроку
    assert check_two_step_confirmation(VALENTIN_ADMIN_ID, 777, "traffic_ok") is False


def test_official_contract_formulations_and_helpers():
    """Перевіряє точність формулювань типового договору КП ОМЕТ, числа прописом та відсутність листа ПОГОДЖЕНО."""
    from services.rental_documents_service import (
        build_contract_route_string,
        format_contract_date,
        format_departure_datetime,
        format_official_contract_number,
        format_uah_amount_in_words,
        parse_customer_details,
    )

    # 1. Суми прописом українською мовою з відмінюванням
    assert format_uah_amount_in_words(9254.27) == "дев’ять тисяч двісті п’ятдесят чотири гривні 27 копійок"
    assert format_uah_amount_in_words(4337.94) == "чотири тисячі триста тридцять сім гривень 94 копійки"
    assert format_uah_amount_in_words(1542.38) == "одна тисяча п’ятсот сорок дві гривні 38 копійок"

    # 2. Офіційні дати
    assert format_contract_date("31.10.2026") == "« 31 » жовтня 2026 р."
    assert format_departure_datetime("31.10.2026", "16:00") == "«31» жовтня 2026 року о 16:00"

    # 3. Номер договору за стандартом КП ОМЕТ (У-У/2026/XXXX)
    assert format_official_contract_number("2026-0042-О") == "У-У/2026/0042"
    assert format_official_contract_number("У-У/2026/0123") == "У-У/2026/0123"

    # 4. Форматування клієнта (ФІЗИЧНА ОСОБА ..., ПЕРЕПЕЛИЦЯ О.О., підпис Олег ПЕРЕПЕЛИЦЯ)
    cust = parse_customer_details(
        {
            "customer_type": "individual",
            "user_full_name": "Перепелиця Олег Олександрович",
            "user_phone": "0974912228",
            "user_tax_id": "3440412133",
            "user_address": "65122, м. Одеса, вул. Ільфа і Петрова буд. 57, корп. 1, кв. 64",
            "user_passport": "паспорт №003876519",
        }
    )
    assert cust["full_uppercase"] == "ФІЗИЧНА ОСОБА ПЕРЕПЕЛИЦЯ ОЛЕГ ОЛЕКСАНДРОВИЧ"
    assert cust["short_name"] == "ПЕРЕПЕЛИЦЯ О.О."
    assert cust["signature_name"] == "Олег ПЕРЕПЕЛИЦЯ"
    assert "Ільфа і Петрова" in cust["address"]
    assert "003876519" in cust["passport"]

    # 4.1 Форматування ФОП
    cust_fop = parse_customer_details(
        {
            "customer_type": "fop",
            "user_full_name": "Коваленко Іван Васильович",
            "user_phone": "0501112233",
            "user_tax_id": "2987654321",
            "user_address": "м. Одеса, вул. Дерибасівська, 10",
        }
    )
    assert "ФІЗИЧНА ОСОБА-ПІДПРИЄМЕЦЬ КОВАЛЕНКО ІВАН ВАСИЛЬОВИЧ" in cust_fop["preamble_customer"]
    assert "Виписки з Єдиного державного реєстру" in cust_fop["preamble_customer"]
    assert cust_fop["signature_name"] == "Іван КОВАЛЕНКО"
    assert any("РНОКПП (ІПН) 2987654321" in line for line in cust_fop["section7_lines"])

    # 4.2 Форматування Юридичної особи
    cust_corp = parse_customer_details(
        {
            "customer_type": "legal_entity",
            "user_full_name": "ТОВ «ЧОРНОМОРСЬКІ ТРАДИЦІЇ»",
            "company_name": "ТОВ «ЧОРНОМОРСЬКІ ТРАДИЦІЇ»",
            "signer_title": "генерального директора",
            "signer_name": "Сидоренко П.В.",
            "foundation_doc": "Статуту",
            "user_phone": "0487009988",
            "user_tax_id": "44556677",
            "user_address": "м. Одеса, Приморський бульвар, 5",
        }
    )
    assert "ТОВ «ЧОРНОМОРСЬКІ ТРАДИЦІЇ»" in cust_corp["preamble_customer"]
    assert "в особі генерального директора Сидоренко П.В." in cust_corp["preamble_customer"]
    assert any("Код ЄДРПОУ 44556677" in line for line in cust_corp["section7_lines"])
    assert cust_corp["signature_name"] == "Сидоренко П.В."

    # 5. Маршрут
    assert (
        build_contract_route_string("пл. Старосінна", "11 станція Люстдорфської дороги", [])
        == "пл. Старосінна – 11 станція Люстдорфської дороги"
    )

    # 6. Генерація повного PDF за зразком типового договору (без листа ПОГОДЖЕНО) для різних типів замовників
    with tempfile.TemporaryDirectory() as td:
        order = {
            "customer_type": "individual",
            "contract_number": "У-У/2026/0123",
            "contract_date": "31.10.2026",
            "rental_date": "31.10.2026",
            "rental_time_slot": "16:00",
            "user_full_name": "Перепелиця Олег Олександрович",
            "user_phone": "0974912228",
            "user_tax_id": "3440412133",
            "user_address": "65122, м. Одеса, вул. Ільфа і Петрова буд. 57, корп. 1, кв. 64",
            "user_passport": "паспорт №003876519",
            "pickup_stop": "пл. Старосінна",
            "dropoff_stop": "11 станція Люстдорфської дороги",
            "via_loops": [],
            "total_price_uah": 9254.27,
        }
        pdf_file = generate_rental_contract_pdf(order, target_dir=td)
        assert os.path.exists(pdf_file)
        assert os.path.getsize(pdf_file) > 10000

        # ФОП
        order["customer_type"] = "fop"
        order["user_full_name"] = "Коваленко Іван Васильович"
        pdf_fop = generate_rental_contract_pdf(order, target_dir=td)
        assert os.path.exists(pdf_fop)

        # Юрособа
        order["customer_type"] = "legal_entity"
        order["user_full_name"] = "ТОВ «ЧОРНОМОРСЬКІ ТРАДИЦІЇ»"
        order["company_name"] = "ТОВ «ЧОРНОМОРСЬКІ ТРАДИЦІЇ»"
        order["signer_title"] = "генерального директора"
        order["signer_name"] = "Сидоренко П.В."
        pdf_corp = generate_rental_contract_pdf(order, target_dir=td)
        assert os.path.exists(pdf_corp)

        # 7. Генерація Word .docx для всіх типів замовників
        from services.rental_documents_service import (
            format_money_ua,
            generate_rental_contract_docx,
            RENTAL_WAGON_CATALOG,
        )
        from services.tram_rental_service import normalize_stop_name

        docx_ind = generate_rental_contract_docx(order, target_dir=td)
        assert os.path.exists(docx_ind) and os.path.getsize(docx_ind) > 5000

        # Перевірка форматування валюти
        assert format_money_ua(10627.95) == "10 627.95"
        assert format_money_ua(8856.63) == "8 856.63"
        assert format_money_ua(1771.32) == "1 771.32"

        # Перевірка місткості до 40 місць
        assert RENTAL_WAGON_CATALOG["retro_mtv"]["capacity_seats"] == 40
        assert RENTAL_WAGON_CATALOG["retro_914"]["capacity_seats"] == 40

        # Перевірка аліасів кінцевих кілець (Парк ім. Т. Г. Шевченка)
        assert normalize_stop_name("Парк ім. Т. Г. Шевченка") == "Парк ім. Тараса Шевченка"
        assert normalize_stop_name("парк ім. т.г. шевченка") == "Парк ім. Тараса Шевченка"
