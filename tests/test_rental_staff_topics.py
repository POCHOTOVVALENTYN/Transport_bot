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

    # Тест завантаження та збереження конфігурації із відновленням початкового стану
    orig_cfg = _load_runtime_staff_config()
    cfg = _load_runtime_staff_config()
    assert "topics" in cfg
    for k in TOPIC_KEYS:
        assert k in cfg["topics"]

    try:
        cfg["topics"]["vuptap"] = 12345
        _save_runtime_staff_config(cfg)
        assert get_staff_topic_thread_id("vuptap") == 12345
    finally:
        _save_runtime_staff_config(orig_cfg)


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


@pytest.mark.asyncio
async def test_legal_revisions_fire_safety_and_department_comments():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from handlers.rental_staff_handlers import (
        build_vuptap_order_keyboard,
        build_legal_order_keyboard,
        build_accounting_order_keyboard,
        build_depot_order_keyboard,
        handle_rental_staff_callback,
        handle_staff_group_text_input,
    )

    db = await _create_test_db()
    now_dt = datetime.datetime(2026, 11, 11, 12, 0)
    order = await db.create_rental_order(
        {
            "user_id": 7453894165,
            "user_full_name": "Іваненко Олена Сергіївна",
            "user_phone": "+380671112233",
            "user_tax_id": "1234567890",
            "user_passport": "КК 123456",
            "user_address": "м. Одеса, вул. Канатна, 10",
            "customer_type": "individual",
            "wagon_type": "Ретро-трамвай МТВ-82",
            "rental_date": "25.11.2026",
            "rental_time_slot": "14:00",
            "pickup_stop": "Аркадія",
            "dropoff_stop": "пл. Старосінна",
            "total_duration_min": 60,
            "total_distance_km": 12.4,
            "total_price_uah": 4337.94,
            "depot_code": "ТД-1",
            "safety_accepted_at": now_dt,
            "status": "pending_depot_time",
        }
    )

    # 1. Етап 1: Погодження часу подачі в Депо
    depot_stage1_text = await format_depot_card_text(order)
    assert "ЕТАП 1: ПОГОДЖЕННЯ ЧАСУ ПОДАЧІ ВАГОНА" in depot_stage1_text
    d_stage1_kb = build_depot_order_keyboard(order)
    d_stage1_callbacks = [b.callback_data for row in d_stage1_kb.inline_keyboard for b in row]
    assert f"rental_staff:depot_time_ok:{order.id}" in d_stage1_callbacks
    assert f"rental_staff:depot_time_alt:{order.id}" in d_stage1_callbacks
    assert f"rental_staff:vuptap_ok:{order.id}" not in d_stage1_callbacks

    # Переводимо у стан після погодження часу Депо
    order = await db.update_rental_order_fields(
        order.id,
        {
            "depot_time_approved_by": "Диспетчер ТД-1",
            "status": "awaiting_signature",
        },
    )

    vuptap_text = await format_vuptap_summary_card_text(order)
    legal_text = await format_legal_card_text(order)
    acc_text = await format_accounting_card_text(order)
    depot_text = await format_depot_card_text(order)

    assert "Прийнято клієнтом" in vuptap_text
    assert "КК 123456" in legal_text
    assert "м. Одеса, вул. Канатна, 10" in legal_text
    assert "UA903281680000000026000122581" in acc_text
    assert "ЧАС ПОГОДЖЕНО" in depot_text

    l_kb = build_legal_order_keyboard(order)
    d_kb = build_depot_order_keyboard(order)

    l_callbacks = [b.callback_data for row in l_kb.inline_keyboard for b in row]
    assert f"rental_staff:legal_upload_dir:{order.id}" in l_callbacks
    assert f"rental_staff:legal_revision:{order.id}" in l_callbacks
    assert f"rental_staff:comment_client:{order.id}:legal" in l_callbacks

    d_callbacks = [b.callback_data for row in d_kb.inline_keyboard for b in row]
    assert f"rental_staff:depot_assign:{order.id}" in d_callbacks
    assert f"rental_staff:vuptap_ok:{order.id}" not in d_callbacks

    # 2. Сценарій повернення договору на правки Юридичним відділом (через попереднє підтвердження)
    bot_mock = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=101)),
        edit_message_text=AsyncMock(),
        send_document=AsyncMock(return_value=SimpleNamespace(message_id=102)),
        send_photo=AsyncMock(return_value=SimpleNamespace(message_id=103)),
    )
    context = SimpleNamespace(bot=bot_mock)

    query_rev = SimpleNamespace(
        data=f"rental_staff:legal_revision:{order.id}",
        message=SimpleNamespace(message_thread_id=13),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update_rev_click = SimpleNamespace(
        callback_query=query_rev,
        effective_user=SimpleNamespace(id=830196453, full_name="Юрист КП ОМЕТ", username="lawyer"),
        effective_chat=SimpleNamespace(id=-1004341305179),
    )
    await handle_rental_staff_callback(update_rev_click, context)

    # Юрист вводить текст зауваження -> отримує вікно перевірки перед відправкою
    msg_rev_input = SimpleNamespace(
        text="Уточніть орган, що видав паспорт КК 123456, та дату видачі.",
        caption=None,
        document=None,
        photo=None,
        message_thread_id=13,
        reply_to_message=None,
        reply_text=AsyncMock(),
    )
    update_rev_text = SimpleNamespace(
        message=msg_rev_input,
        effective_user=SimpleNamespace(id=830196453, full_name="Юрист КП ОМЕТ", username="lawyer"),
        effective_chat=SimpleNamespace(id=-1004341305179),
    )
    handled = await handle_staff_group_text_input(update_rev_text, context)
    assert handled is True

    # Підтверджуємо відправку зауваження клієнту
    query_confirm_rev = SimpleNamespace(
        data=f"rental_staff:confirm_send_msg:{order.id}",
        message=SimpleNamespace(message_thread_id=13),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update_confirm_rev = SimpleNamespace(
        callback_query=query_confirm_rev,
        effective_user=SimpleNamespace(id=830196453, full_name="Юрист КП ОМЕТ", username="lawyer"),
        effective_chat=SimpleNamespace(id=-1004341305179),
    )
    await handle_rental_staff_callback(update_confirm_rev, context)

    updated_order = await db.get_rental_order(order.id)
    assert updated_order.status == "revision_requested"

    # 3. Сценарій коментаря клієнту від Бухгалтерії (також із попереднім уточненням)
    query_comm = SimpleNamespace(
        data=f"rental_staff:comment_client:{order.id}:accounting",
        message=SimpleNamespace(message_thread_id=14),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update_comm_click = SimpleNamespace(
        callback_query=query_comm,
        effective_user=SimpleNamespace(id=830196453, full_name="Головний бухгалтер", username="acc"),
        effective_chat=SimpleNamespace(id=-1004341305179),
    )
    await handle_rental_staff_callback(update_comm_click, context)

    msg_comm_input = SimpleNamespace(
        text="Будь ласка, вкажіть номер договору у призначенні платежу.",
        caption=None,
        document=None,
        photo=None,
        message_thread_id=14,
        reply_to_message=None,
        reply_text=AsyncMock(),
    )
    update_comm_text = SimpleNamespace(
        message=msg_comm_input,
        effective_user=SimpleNamespace(id=830196453, full_name="Головний бухгалтер", username="acc"),
        effective_chat=SimpleNamespace(id=-1004341305179),
    )
    assert await handle_staff_group_text_input(update_comm_text, context) is True

    query_confirm_comm = SimpleNamespace(
        data=f"rental_staff:confirm_send_msg:{order.id}",
        message=SimpleNamespace(message_thread_id=14),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update_confirm_comm = SimpleNamespace(
        callback_query=query_confirm_comm,
        effective_user=SimpleNamespace(id=830196453, full_name="Головний бухгалтер", username="acc"),
        effective_chat=SimpleNamespace(id=-1004341305179),
    )
    await handle_rental_staff_callback(update_confirm_comm, context)

    # 4. Перевірка Етапу 3А (завантаження договору з підписом Директора) та Етапу 3Б (оплата з попередженням) -> Етап 4
    query_dir = SimpleNamespace(
        data=f"rental_staff:legal_upload_dir:{order.id}",
        message=SimpleNamespace(message_thread_id=13),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    await handle_rental_staff_callback(
        SimpleNamespace(
            callback_query=query_dir,
            effective_user=SimpleNamespace(id=830196453, full_name="Юрист КП ОМЕТ", username="lawyer"),
            effective_chat=SimpleNamespace(id=-1004341305179),
        ),
        context,
    )
    msg_dir_doc = SimpleNamespace(
        text="",
        caption=None,
        document=SimpleNamespace(file_id="dir_signed_file_123", file_name="Contract_Director_Signed.pdf"),
        photo=None,
        message_thread_id=13,
        reply_to_message=None,
        reply_text=AsyncMock(),
    )
    assert await handle_staff_group_text_input(
        SimpleNamespace(
            message=msg_dir_doc,
            effective_user=SimpleNamespace(id=830196453, full_name="Юрист КП ОМЕТ", username="lawyer"),
            effective_chat=SimpleNamespace(id=-1004341305179),
        ),
        context,
    ) is True

    # Підтверджуємо відправку підписаного Директором договору клієнту
    await handle_rental_staff_callback(
        SimpleNamespace(
            callback_query=SimpleNamespace(
                data=f"rental_staff:confirm_dir_doc:{order.id}",
                message=SimpleNamespace(message_thread_id=13),
                answer=AsyncMock(),
                edit_message_text=AsyncMock(),
            ),
            effective_user=SimpleNamespace(id=830196453, full_name="Юрист КП ОМЕТ", username="lawyer"),
            effective_chat=SimpleNamespace(id=-1004341305179),
        ),
        context,
    )

    # Бухгалтерія підтверджує оплату
    await handle_rental_staff_callback(
        SimpleNamespace(
            callback_query=SimpleNamespace(
                data=f"rental_staff:confirm_acc_ok:{order.id}",
                message=SimpleNamespace(message_thread_id=14),
                answer=AsyncMock(),
                edit_message_text=AsyncMock(),
            ),
            effective_user=SimpleNamespace(id=830196453, full_name="Головний бухгалтер", username="acc"),
            effective_chat=SimpleNamespace(id=-1004341305179),
        ),
        context,
    )

    ready_order = await db.get_rental_order(order.id)
    depot_ready_text = await format_depot_card_text(ready_order)
    assert "🟢 ЗАЯВКА НА ВИПУСК ВАГОНА АКТИВОВАНО" in depot_ready_text

    logs = await db.get_rental_audit_logs(order.id, limit=15)
    actions = [lg.action for lg in logs]
    assert "LEGAL_REVISION_REQUESTED" in actions
    assert "STAFF_COMMENT_CLIENT" in actions
    assert "DIRECTOR_CONTRACT_SENT" in actions
    assert "PAYMENT_CONFIRMED" in actions
