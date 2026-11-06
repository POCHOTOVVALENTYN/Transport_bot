"""
Тести для функціоналу форум-тем штабного чату КП «ОМЕТ»,
пульту керування слотами Депо та інтерактивної аналітики.
"""

import os
import pytest
import datetime
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base, Database
import handlers.rental_staff_handlers as staff_handlers
from handlers.rental_staff_handlers import (
    TOPIC_KEYS,
    TOPIC_TITLES_UA,
    _load_runtime_staff_config,
    _save_runtime_staff_config,
    get_staff_topic_thread_id,
    format_vuptap_summary_card_text,
    format_legal_card_text,
    format_accounting_card_text,
    format_depot_card_text,
    render_period_analytics_text,
    render_recent_orders_menu,
    render_order_timeline_text,
    render_recent_actions_text,
    render_depot_slots_menu,
    render_analytics_main_menu,
)


async def _create_test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    test_db = Database()
    test_db.session_factory = session_factory
    staff_handlers.db = test_db
    return test_db


@pytest.mark.asyncio
async def test_depot_slot_management_db():
    db = await _create_test_db()
    test_date = "25.12.2026"

    # 1. Додавання слотів через Депо
    added = await db.add_rental_slots(
        rental_date=test_date,
        slot_times=["10:00", "14:00", "17:30"],
        transport_type="retro_tram",
        added_by_id=830196453,
        added_by_name="Валентин (Адміністратор)",
    )
    assert len(added) == 3

    # 2. Отримання дат з вільними слотами
    free_dates = await db.get_dates_with_free_slots()
    assert test_date in free_dates

    # 3. Отримання всіх слотів на дату
    all_slots = await db.get_all_rental_slots_for_date(test_date)
    assert len(all_slots) >= 3
    times = [s.slot_time for s in all_slots]
    assert "10:00" in times
    assert "14:00" in times
    assert "17:30" in times

    # 4. Видалення одного вільного слота
    target_slot = next(s for s in all_slots if s.slot_time == "14:00")
    del_ok = await db.delete_rental_slot_by_id(target_slot.id)
    assert del_ok is True

    # Перевіряємо, що 14:00 більше немає
    remaining_slots = await db.get_all_rental_slots_for_date(test_date)
    rem_times = [s.slot_time for s in remaining_slots]
    assert "14:00" not in rem_times
    assert "10:00" in rem_times
    assert "17:30" in rem_times

    # 5. Очищення залишків для чистоти тестів
    for s in remaining_slots:
        if s.rental_date == test_date:
            await db.delete_rental_slot_by_id(s.id)


@pytest.mark.asyncio
async def test_topic_configuration_helpers():
    # Перевірка наявності всіх необхідних тем
    assert "vuptap" in TOPIC_KEYS
    assert "depot" in TOPIC_KEYS
    assert "accounting" in TOPIC_KEYS
    assert "legal" in TOPIC_KEYS
    assert "analytics" in TOPIC_KEYS
    assert "general" not in TOPIC_KEYS  # General вилучено за узгодженням

    # Тест завантаження та збереження конфігурації
    cfg = _load_runtime_staff_config()
    assert "topics" in cfg
    for k in TOPIC_KEYS:
        assert k in cfg["topics"]

    # Зберігаємо тестовий thread_id для vuptap
    cfg["topics"]["vuptap"] = 12345
    _save_runtime_staff_config(cfg)
    assert get_staff_topic_thread_id("vuptap") == 12345

    # Скидаємо назад
    cfg["topics"]["vuptap"] = None
    _save_runtime_staff_config(cfg)
    assert get_staff_topic_thread_id("vuptap") is None


@pytest.mark.asyncio
async def test_analytics_and_audit_timeline():
    db = await _create_test_db()
    order_data = {
        "user_id": 830196453,
        "user_full_name": "Тестовий Замовник Валентин",
        "user_phone": "+380501234567",
        "customer_type": "individual",
        "wagon_type": "Ретро-трамвай МТВ-82",
        "rental_date": "20.11.2026",
        "rental_time_slot": "12:00",
        "route_mode": "custom_loop",
        "route_display_name": "Аркадія - пл. Старосінна",
        "pickup_stop": "Аркадія",
        "dropoff_stop": "пл. Старосінна",
        "waiting_time_minutes": 10,
        "signing_scenario": "diia",
        "total_duration_minutes": 90,
        "total_distance_km": 15.5,
        "total_price_uah": 6500.0,
        "calculated_hours": 1.5,
        "depot_code": "ВРМ",
        "pickup_deadhead_km": 2.5,
        "pickup_deadhead_min": 15,
        "main_route_km": 10.5,
        "main_route_min": 60,
        "return_deadhead_km": 2.5,
        "return_deadhead_min": 15,
    }
    order = await db.create_rental_order(order_data)
    assert order.id is not None
    assert order.contract_number is not None

    # Додаємо записи аудиту від імені служб
    await db.add_rental_audit_log(
        order_id=order.id,
        actor_id=830196453,
        actor_name="Валентин (ВУПтаП)",
        actor_role="ВУПтаП",
        action="VUPTAP_APPROVED",
        details="Погоджено безпеку руху та графік рейсу",
    )
    await db.add_rental_audit_log(
        order_id=order.id,
        actor_id=111,
        actor_name="Юрист КП",
        actor_role="Юридичний відділ",
        action="LEGAL_APPROVED",
        details="Договір підписано через Дія.Підпис",
    )
    await db.add_rental_audit_log(
        order_id=order.id,
        actor_id=222,
        actor_name="Бухгалтер КП",
        actor_role="Бухгалтерія",
        action="PAYMENT_CONFIRMED",
        details="Підтверджено оплату 6500.00 грн за IBAN",
    )

    # Оновлюємо статус замовлення до paid_confirmed
    await db.update_rental_order_fields(order.id, {"status": "paid_confirmed"})

    # Перевіряємо періодичну аналітику
    stats = await db.get_rental_period_analytics(days=7)
    assert stats["total_orders"] >= 1
    assert stats["total_revenue_uah"] >= 6500.0
    assert stats["mtv_count"] >= 1

    # Перевіряємо таймлайн замовлення
    timeline = await db.get_order_timeline_analytics(order.id)
    assert timeline is not None
    assert timeline["order"].id == order.id
    assert len(timeline["logs"]) >= 4  # ORDER_CREATED + 3 доданих вище

    # Перевіряємо текстові рендерери
    period_text = await render_period_analytics_text(days=7)
    assert "ЗВІДНИЙ ЗВІТ МОДУЛЯ ОРЕНДИ" in period_text
    assert "6,500.00 грн" in period_text or "6500" in period_text

    orders_text, orders_kb = await render_recent_orders_menu()
    assert "АНАЛІТИКА ОКРЕМИХ ЗАМОВЛЕНЬ" in orders_text
    assert len(orders_kb.inline_keyboard) >= 2

    timeline_text, timeline_kb = await render_order_timeline_text(order.id)
    assert f"№ {order.contract_number}" in timeline_text
    assert "ТАЙМЛАЙН ДІЙ ПІДРОЗДІЛІВ" in timeline_text

    actions_text, actions_kb = await render_recent_actions_text()
    assert "ЖУРНАЛ ОСТАННІХ ДІЙ ПЕРСОНАЛУ" in actions_text

    # Перевіряємо меню слотів та меню аналітики
    depot_menu_text, depot_menu_kb = render_depot_slots_menu()
    assert "ПУЛЬТ КЕРУВАННЯ СЛОТАМИ" in depot_menu_text

    analytics_menu_text, analytics_menu_kb = render_analytics_main_menu()
    assert "АНАЛІТИЧНИЙ ПУЛЬТ ОРЕНДИ ТРАМВАЇВ" in analytics_menu_text
