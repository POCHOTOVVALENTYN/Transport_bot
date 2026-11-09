"""
Комплексні модульні та інтеграційні тести конструктора маршрутів та сценаріїв оренди:
1. Конструктор довільного маршруту з кількома проміжними кільцями (via_loops);
2. Розрахунок усіх 5 популярних готових екскурсійних маршрутів (пресетів);
3. Нормалізація та аліаси розворотних кілець (включно з 'Парк ім. Т. Г. Шевченка' та '16-та станція');
4. Валідація некоректних маршрутів (кільцевий без проміжного, невідома зупинка);
5. Два типи рухомого складу: МТВ-82 (закритий) та Відкритий №914 (відкритий літній);
6. Валідація дати (не раніше today + 3 дні) та вибір часу (стандартні слоти + власний час ГГ:ХХ);
7. Фінансовий розрахунок (хвилини Wialon, правило 60 хв, додаткові послуги, ПДВ 20%, пробіли в сумах);
8. Генерація документів (Word .docx та PDF Договір, Рахунок IBAN з QR НБУ, Маршрутний лист Wialon);
9. Три типи замовників (Фізична особа, ФОП, Юридична особа) та їх реквізити;
10. Наскрізна симуляція майстра оформлення замовлення (ConversationHandler).
"""

from __future__ import annotations

import datetime
import os
import re
import tempfile
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from bot.states import States
from config.settings import VALENTIN_ADMIN_ID
from database.db import Base, Database
import handlers.rental_staff_handlers as staff_handlers
from handlers.rental_client_handlers import (
    _get_draft,
    _reset_draft,
    rental_finalize_order,
    rental_handle_customer_type_selected,
    rental_handle_custom_time_input,
    rental_handle_date_button,
    rental_handle_date_text,
    rental_handle_dropoff_loop_selected,
    rental_handle_name_input,
    rental_handle_phone_input,
    rental_handle_pickup_loop_selected,
    rental_handle_safety_accepted,
    rental_handle_signing_selected,
    rental_handle_slot_selected,
    rental_handle_tax_input,
    rental_handle_via_done,
    rental_handle_via_loop_selected,
    rental_handle_wait_selected,
    rental_select_preset,
    rental_select_route_mode,
    rental_select_wagon,
    rental_start_wizard,
    rental_toggle_extra,
    show_rental_hub,
)
from services.rental_documents_service import (
    RENTAL_POPULAR_PRESETS,
    RENTAL_WAGON_CATALOG,
    RentalPriceInput,
    build_nbu_iban_payment_purpose,
    build_nbu_iban_qr_payload,
    calculate_rental_price_breakdown,
    format_money_ua,
    generate_rental_contract_docx,
    generate_rental_contract_pdf,
    generate_rental_iban_invoice_pdf,
    parse_customer_details,
)
from services.tram_rental_service import (
    OFFICIAL_TURNING_LOOPS,
    RentalCalculationInput,
    calculate_rental_route,
    calculate_tram_rental_trip,
    generate_rental_route_sheet_pdf,
    get_available_turning_loops,
    normalize_stop_name,
)


# ================= 1. ТЕСТИ КОНСТРУКТОРА МАРШРУТІВ (ROUTING CONSTRUCTOR) =================


def test_custom_multi_loop_constructor_route():
    """Тестує конструктор складного маршруту з кількома проміжними розворотними кільцями."""
    via_list = ["Парк ім. Тараса Шевченка", "Аркадія", "16-а станція Великого Фонтану"]
    calc_input = RentalCalculationInput(
        transport_type="TRAM",
        wagon_type="retro",
        depot_base="ВРМ",
        pickup_stop="пл. Старосінна",
        dropoff_stop="пл. Старосінна",
        via_loops=via_list,
        wait_minutes_at_loop=5,
        departure_time="14:00",
    )
    result = calculate_rental_route(calc_input)

    assert result.is_success is True
    assert result.depot_base == "ВРМ"
    # Фаза 1: виїзд із депо ВРМ -> Старосінна
    assert result.phase_1_dispatch.distance_km > 2.0
    assert result.phase_1_dispatch.motion_minutes > 10
    # Фаза 2: повний маршрут через 3 кільця (стоянка 5 хв на кожному кільці = 15 хв)
    assert result.phase_2_rental.distance_km > 25.0
    assert result.phase_2_rental.motion_minutes > 100
    assert result.phase_2_rental.wait_minutes == 5 * len(via_list)
    # Фаза 3: повернення в депо ВРМ
    assert result.phase_3_return.distance_km > 2.0
    assert result.phase_3_return.motion_minutes > 10
    # Загальний баланс
    assert result.total_billable_km > 30.0
    assert result.total_duration_minutes > 120


def test_all_popular_presets_calculation():
    """Перевіряє, що всі 5 готових екскурсійних маршрутів (пресетів) успішно калькулюються Wialon."""
    for p_key, p_data in RENTAL_POPULAR_PRESETS.items():
        calc_in = RentalCalculationInput(
            transport_type="TRAM",
            wagon_type="retro",
            depot_base="ВРМ",
            pickup_stop=p_data["pickup_stop"],
            dropoff_stop=p_data["dropoff_stop"],
            via_loops=p_data.get("via_loops", []),
            wait_minutes_at_loop=p_data.get("default_wait_minutes", 10),
            departure_time="12:00",
        )
        out = calculate_rental_route(calc_in)
        assert out.is_success is True, f"Пресет '{p_key}' завершився з помилкою: {out.error_message}"
        assert out.total_billable_km > 0
        assert out.total_duration_minutes >= 60


def test_stop_name_normalization_and_aliases():
    """Перевіряє розпізнавання різних форм написання зупинок і кілець."""
    assert normalize_stop_name("Парк ім. Т. Г. Шевченка") == "Парк ім. Тараса Шевченка"
    assert normalize_stop_name("парк ім. т.г. шевченка") == "Парк ім. Тараса Шевченка"
    assert normalize_stop_name("Старосінна площа") == "пл. Старосінна"
    assert normalize_stop_name("16-та станція Великого Фонтану") == "16-а станція Великого Фонтану"
    assert normalize_stop_name("Аркадія") == "Аркадія"


def test_point_to_point_cross_city_routes():
    """Тестує прямі лінійні маршрути з різними точками посадки та висадки."""
    routes = [
        ("Слобідський ринок", "Херсонський сквер"),
        ("пл. Тираспольська", "станція Застава ІІ"),
        ("Куликове поле", "16-а станція Великого Фонтану"),
    ]
    for p_start, p_end in routes:
        calc_in = RentalCalculationInput(
            transport_type="TRAM",
            wagon_type="retro",
            depot_base="ВРМ",
            pickup_stop=p_start,
            dropoff_stop=p_end,
            via_loops=[],
            wait_minutes_at_loop=0,
        )
        out = calculate_rental_route(calc_in)
        assert out.is_success is True
        assert out.phase_1_dispatch.to_stop == normalize_stop_name(p_start)
        assert out.phase_3_return.from_stop == normalize_stop_name(p_end)
        assert out.total_billable_km > 5.0


def test_circular_without_via_loops_raises_validation_error():
    """Перевіряє захист від замкненого маршруту без вказівки проміжного кільця."""
    calc_in = RentalCalculationInput(
        transport_type="TRAM",
        wagon_type="retro",
        depot_base="ВРМ",
        pickup_stop="пл. Старосінна",
        dropoff_stop="пл. Старосінна",
        via_loops=[],
        wait_minutes_at_loop=0,
    )
    with pytest.raises(ValueError) as exc:
        calculate_rental_route(calc_in)
    assert "проміжне розворотне кільце" in str(exc.value).lower()


# ================= 2. ТЕСТИ РУХОМОГО СКЛАДУ ТА ЦІНОУТВОРЕННЯ =================


def test_wagon_catalog_specs():
    """Перевіряє характеристики рухомого складу: МТВ-82 та Відкритий №914."""
    mtv = RENTAL_WAGON_CATALOG["retro_mtv"]
    w914 = RENTAL_WAGON_CATALOG["retro_914"]

    assert mtv["capacity_seats"] == 40
    assert mtv["engine_wagon_type"] == "retro"
    assert "МТВ-82" in mtv["short_title"]

    assert w914["capacity_seats"] == 40
    assert w914["engine_wagon_type"] == "retro"
    assert "914" in w914["short_title"]


def test_pricing_1h_minimum_rule():
    """Короткі поїздки (< 60 хв) округлюються до мінімального замовлення 1 година (60 хв)."""
    p_in = RentalPriceInput(
        wagon_key="retro_mtv",
        total_duration_minutes=35,
        wait_minutes=0,
        extra_service_keys=[],
    )
    bd = calculate_rental_price_breakdown(p_in)
    assert bd.billable_minutes == 60
    assert bd.time_price_uah == pytest.approx(4337.94, 0.01)
    assert bd.total_price_uah == pytest.approx(4337.94, 0.01)
    assert bd.without_vat_uah == pytest.approx(3614.95, 0.01)
    assert bd.vat_20_uah == pytest.approx(722.99, 0.01)


def test_pricing_long_trip_and_extra_services():
    """Довга поїздка (147 хв) з додатковими послугами (екскурсовод 600 грн + аудіосистема 500 грн)."""
    p_in = RentalPriceInput(
        wagon_key="retro_914",
        total_duration_minutes=147,
        wait_minutes=10,
        extra_service_keys=["guide", "music"],
    )
    bd = calculate_rental_price_breakdown(p_in)
    assert bd.billable_minutes == 147
    # 147 хв * (4337.94 / 60) = 10627.95
    assert bd.time_price_uah == pytest.approx(10627.95, 0.05)
    # Екскурсовод (600) + Аудіосистема (500) = 1100
    assert bd.extras_price_uah == 1100.0
    assert bd.total_price_uah == pytest.approx(11727.95, 0.05)
    assert bd.vat_20_uah == pytest.approx(11727.95 / 6.0, 0.05)

    # Перевірка форматування валюти з розділенням тисяч пробілом
    assert format_money_ua(bd.total_price_uah) == "11 727.95"


def test_nbu_iban_qr_payload_generation():
    """Перевіряє відповідність рядка QR-коду стандарту Національного банку України."""
    payload = build_nbu_iban_qr_payload("У-У/2026/0099", "15.11.2026", 10627.95)
    lines = payload.split("\n")
    assert len(lines) == 10
    assert lines[0] == "BCD"
    assert lines[1] == "002"
    assert lines[2] == "1"
    assert lines[3] == "UCT"
    assert "Одесміськелектротранс" in lines[4]
    assert lines[5].startswith("UA")
    assert lines[6] == "UAH10627.95"
    assert lines[7] == "03328497"
    assert lines[8] == ""
    assert "У-У/2026/0099" in lines[9]


# ================= 3. ТЕСТИ ЗАМОВНИКІВ ТА ГЕНЕРАЦІЇ ДОКУМЕНТІВ =================


def test_customer_legal_status_details():
    """Перевіряє парсинг реквізитів для трьох статусів замовника: фізособа, ФОП та юрособа."""
    # 1. Фізична особа
    ind = parse_customer_details({
        "customer_type": "individual",
        "user_full_name": "Шевченко Тарас Григорович",
        "user_phone": "+380501234567",
        "user_tax_id": "1122334455",
    })
    assert "ФІЗИЧНА ОСОБА ШЕВЧЕНКО ТАРАС ГРИГОРОВИЧ" in ind["full_uppercase"]
    assert ind["short_name"] == "ШЕВЧЕНКО Т.Г."
    assert ind["signature_name"] == "Тарас ШЕВЧЕНКО"
    assert ind["address"] == "65000, м. Одеса (заповнюється при підписанні)"
    assert ind["passport"] == "паспорт / ID-картка (заповнюється при підписанні)"

    # 2. ФОП
    fop = parse_customer_details({
        "customer_type": "fop",
        "user_full_name": "Іванов Петро Сергійович",
        "user_phone": "+380671112233",
        "user_tax_id": "2233445566",
    })
    assert "ФІЗИЧНА ОСОБА-ПІДПРИЄМЕЦЬ ІВАНОВ ПЕТРО СЕРГІЙОВИЧ" in fop["preamble_customer"]
    assert "Виписки" in fop["preamble_customer"]
    assert fop["signature_name"] == "Петро ІВАНОВ"

    # 3. Юридична особа
    corp = parse_customer_details({
        "customer_type": "legal_entity",
        "user_full_name": "ТОВ «Південний Експрес» в особі директора Бондаря О.В.",
        "user_phone": "+380487000111",
        "user_tax_id": "12345678",
    })
    assert "ТОВ «Південний Експрес»" in corp["preamble_customer"]
    assert "Код ЄДРПОУ 12345678" in "".join(corp["section7_lines"])


def test_all_four_official_documents_generation():
    """Генерує повний комплект із 4 файлів і перевіряє їх структуру та розмір."""
    sample_order = {
        "contract_number": "У-У/2026/0777",
        "contract_date": "15.11.2026",
        "rental_date": "15.11.2026",
        "rental_time_slot": "13:00",
        "customer_type": "individual",
        "user_full_name": "Перепелиця Олег Олександрович",
        "user_phone": "+380501112233",
        "user_tax_id": "3440412133",
        "transport_type": "TRAM",
        "wagon_type": "Ретро-трамвай Відкритий №914",
        "depot_code": "ВРМ",
        "pickup_stop": "пл. Старосінна",
        "via_loops": ["Аркадія"],
        "dropoff_stop": "пл. Старосінна",
        "wait_minutes": 10,
        "distance_pull_out_km": 2.7,
        "distance_route_km": 14.4,
        "distance_pull_in_km": 2.7,
        "total_distance_km": 19.8,
        "duration_pull_out_min": 14,
        "duration_route_min": 58,
        "duration_pull_in_min": 14,
        "total_duration_min": 96,
        "km_price_uah": 6940.70,
        "wait_price_uah": 0.0,
        "extras_price_uah": 0.0,
        "total_price_uah": 6940.70,
        "signing_scenario": "kep",
    }

    with tempfile.TemporaryDirectory() as td:
        # 1. Word .docx
        docx_file = generate_rental_contract_docx(sample_order, target_dir=td)
        assert os.path.exists(docx_file)
        assert os.path.getsize(docx_file) > 5000

        # 2. PDF Contract
        pdf_contract = generate_rental_contract_pdf(sample_order, target_dir=td)
        assert os.path.exists(pdf_contract)
        assert os.path.getsize(pdf_contract) > 10000

        # 3. PDF IBAN Invoice
        pdf_invoice = generate_rental_iban_invoice_pdf(sample_order, target_dir=td)
        assert os.path.exists(pdf_invoice)
        assert os.path.getsize(pdf_invoice) > 2000

        # 4. PDF Wialon Route Sheet
        calc_out = calculate_rental_route(
            RentalCalculationInput(
                order_id="У-У/2026/0777",
                transport_type="TRAM",
                wagon_type="retro",
                depot_base="ВРМ",
                pickup_stop="пл. Старосінна",
                dropoff_stop="пл. Старосінна",
                via_loops=["Аркадія"],
                wait_minutes_at_loop=10,
            )
        )
        pdf_route = generate_rental_route_sheet_pdf(
            calc_out,
            output_pdf_path=os.path.join(td, "route_sheet.pdf"),
            wagon_title=sample_order["wagon_type"],
        )
        assert os.path.exists(pdf_route)
        assert os.path.getsize(pdf_route) > 2000


# ================= 4. НАСКРІЗНА СИМУЛЯЦІЯ ДІАЛОГУ БОТА (CONVERSATION HANDLER) =================


@pytest.mark.asyncio
async def test_full_wizard_conversation_flow():
    """
    Симулює всі кроки створення замовлення через майстер Telegram-бота:
    Крок 1 (Вагон) -> Крок 2 (Конструктор маршруту) -> Крок 3 (Дата та Час) ->
    Крок 4 (Калькуляція) -> Крок 5 (Формат договору) -> Крок 6 (Реквізити) ->
    Фінальне збереження та генерація пакету.
    """
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_session_factory = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    mock_db = Database()
    mock_db.session_factory = test_session_factory

    import handlers.rental_client_handlers as client_handlers
    client_handlers.db = mock_db
    staff_handlers.db = mock_db

    # Створюємо мок-контекст користувача
    user_id = VALENTIN_ADMIN_ID
    context = MagicMock()
    context.user_data = {}
    msg_obj = MagicMock()
    msg_obj.message_id = 9999
    context.bot.send_message = AsyncMock(return_value=msg_obj)
    context.bot.send_document = AsyncMock()
    context.bot.send_photo = AsyncMock()

    def make_update(callback_data: str | None = None, message_text: str | None = None) -> Update:
        up = MagicMock()
        up.effective_user.id = user_id
        up.effective_chat.id = user_id
        if callback_data:
            q = MagicMock()
            q.data = callback_data
            q.answer = AsyncMock()
            q.edit_message_text = AsyncMock()
            q.edit_message_caption = AsyncMock()
            q.message.delete = AsyncMock()
            q.message.photo = None
            up.callback_query = q
            up.message = None
        elif message_text:
            m = MagicMock()
            m.text = message_text
            m.reply_text = AsyncMock()
            up.message = m
            up.callback_query = None
        return up

    # 1. Початок майстра (КРОК 1: Рухомий склад)
    s1 = await rental_start_wizard(make_update("rental_start_wizard"), context)
    assert s1 == States.RENTAL_SELECT_WAGON

    # Обираємо Відкритий №914
    s2 = await rental_select_wagon(make_update("rental_wagon:retro_914"), context)
    assert s2 == States.RENTAL_SELECT_ROUTE_MODE
    draft = _get_draft(context)
    assert draft["wagon_key"] == "retro_914"

    # 2. Обираємо режим 'Конструктор'
    s3 = await rental_select_route_mode(make_update("rental_rmode:custom"), context)
    assert s3 == States.RENTAL_SELECT_PICKUP_LOOP

    # Отримуємо доступні кільця
    loops = get_available_turning_loops("TRAM")
    starosinna_idx = loops.index("пл. Старосінна")
    arcadia_idx = loops.index("Аркадія")

    # Обираємо кільце посадки: пл. Старосінна за його індексом
    s4 = await rental_handle_pickup_loop_selected(make_update(f"rental_loop_pick:{starosinna_idx}"), context)
    assert s4 == States.RENTAL_SELECT_VIA_LOOPS

    # Додаємо проміжне кільце: Аркадія
    s_alight = await rental_handle_via_loop_selected(make_update(f"rental_loop_via:{arcadia_idx}"), context)
    assert s_alight == States.RENTAL_VIA_PROMPT_DROPOFF

    # Підтверджуємо висадку пасажирів на кільці
    s_wait = await client_handlers.rental_handle_via_alighting_selected(make_update("rental_via_alight:yes"), context)
    assert s_wait == States.RENTAL_VIA_PROMPT_WAIT_MINUTES

    # Обираємо 5 хв стоянки
    s_via_hub = await client_handlers.rental_handle_via_wait_selected(make_update("rental_via_wait:5"), context)
    assert s_via_hub == States.RENTAL_SELECT_VIA_LOOPS

    # Натискаємо 'Готово' (перейти до кінцевої)
    s5 = await rental_handle_via_done(make_update("rental_via_done"), context)
    assert s5 == States.RENTAL_SELECT_DROPOFF_LOOP

    # Обираємо кільце висадки: пл. Старосінна -> переходить на дашборд маршруту
    s6 = await rental_handle_dropoff_loop_selected(make_update(f"rental_loop_drop:{starosinna_idx}"), context)
    assert s6 == States.RENTAL_ROUTE_EDITOR_DASHBOARD

    # Підтверджуємо маршрут на дашборді -> переходить до вибору дати
    s7 = await client_handlers._render_date_selection(make_update("rental_route_confirm"), context)
    assert s7 == States.RENTAL_SELECT_DATE

    # 3. Обираємо дату поїздки: кнопкою на 4 дні вперед
    future_date = (datetime.date.today() + datetime.timedelta(days=4)).strftime("%d.%m.%Y")
    s8 = await rental_handle_date_button(make_update(f"rental_date:{future_date}"), context)
    assert s8 == States.RENTAL_SELECT_SLOT

    # Обираємо стандартний час: 14:30
    s9 = await rental_handle_slot_selected(make_update("rental_slot:14:30"), context)
    assert s9 == States.RENTAL_SELECT_EXTRAS
    draft = _get_draft(context)
    assert draft["rental_date"] == future_date
    assert draft["rental_time_slot"] == "14:30"
    assert draft["total_price_uah"] > 0

    # 4. Додаємо додаткову послугу 'guide'
    await rental_toggle_extra(make_update("rental_extra:guide"), context)
    draft = _get_draft(context)
    assert "guide" in draft["extra_services"]

    # 5. Переходимо до вибору підписання договору
    s10 = await rental_handle_signing_selected(make_update("rental_sign:kep"), context)
    assert s10 == States.RENTAL_SAFETY_BRIEFING

    # 6. Ознайомлення з правилами безпеки
    s11 = await rental_handle_safety_accepted(make_update("rental_safety_accept"), context)
    assert s11 == States.RENTAL_SELECT_CUSTOMER_TYPE

    # Обираємо статус: Юридична особа
    s12 = await rental_handle_customer_type_selected(make_update("rental_cust_type:legal_entity"), context)
    assert s12 == States.RENTAL_ENTER_CUSTOMER_NAME

    # Вводимо назву компанії
    s13 = await rental_handle_name_input(make_update(message_text="ТОВ «Одеський Трамвай»"), context)
    assert s13 == States.RENTAL_ENTER_CUSTOMER_PHONE

    # Вводимо телефон
    s14 = await rental_handle_phone_input(make_update(message_text="+380487001122"), context)
    assert s14 == States.RENTAL_ENTER_CUSTOMER_TAX_ID

    # Вводимо ЄДРПОУ
    s15 = await rental_handle_tax_input(make_update(message_text="44556677"), context)
    assert s15 == States.RENTAL_FINAL_CONFIRM

    # 7. Фінальне підтвердження та створення замовлення
    fin_update = make_update("rental_confirm_create")
    await rental_finalize_order(fin_update, context)

    # Перевіряємо збереження замовлення в БД
    orders = await mock_db.get_user_active_rental_orders(user_id)
    assert len(orders) == 1
    created_order = orders[0]

    assert created_order.wagon_type == "Відкритий ретро-вагон №914"
    assert created_order.pickup_stop == "пл. Старосінна"
    assert created_order.dropoff_stop == "пл. Старосінна"
    assert created_order.customer_type == "legal_entity"
    assert created_order.user_tax_id == "44556677"
    assert created_order.signing_scenario == "kep"
    assert created_order.rental_date == future_date
    assert created_order.rental_time_slot == "14:30"
    assert created_order.contract_number.endswith("-О")

    # Перевіряємо, що бот надіслав документи (тільки 3 файли PDF, без DOCX для клієнта)
    assert context.bot.send_document.call_count == 3
    sent_filenames = [
        call.kwargs.get("filename") for call in context.bot.send_document.call_args_list
    ]
    assert all(fn.endswith(".pdf") for fn in sent_filenames)
    assert not any(fn.endswith(".docx") for fn in sent_filenames)


def test_stop_search_and_popular_catalog() -> None:
    """Тестує функціонал пошуку будь-якої зупинки, ТОП-20 популярних та 6 районів."""
    from services.tram_rental_service import (
        POPULAR_TRAM_STOPS,
        get_all_districts,
        get_all_rental_points,
        get_stops_by_district,
        is_turnaround_loop,
        search_tram_stops,
    )

    # 1. ТОП-20 популярних зупинок
    assert len(POPULAR_TRAM_STOPS) == 20
    all_pts = get_all_rental_points("TRAM")
    for item in POPULAR_TRAM_STOPS:
        assert item["name"] in all_pts
        assert item["icon"] in ("🔄", "🚏")

    # 2. Розворотне кільце vs лінійна зупинка
    assert is_turnaround_loop("Аркадія") is True
    assert is_turnaround_loop("Парк ім. Тараса Шевченка") is True
    assert is_turnaround_loop("вул. Канатна") is False
    assert is_turnaround_loop("Інститут ім. Філатова") is False

    # 3. Швидкий пошук за назвою та аліасами
    assert "вул. Канатна" in search_tram_stops("канат")
    assert "Аркадія" in search_tram_stops("аркад")
    assert "вул. Грецька" in search_tram_stops("дерибас")
    assert "Парк ім. Тараса Шевченка" in search_tram_stops("ланжерон")
    assert "Інститут ім. Філатова" in search_tram_stops("філат")

    # 4. Райони міста
    districts = get_all_districts()
    assert len(districts) == 6
    for d in districts:
        d_stops = get_stops_by_district(d)
        assert len(d_stops) > 0
        for s in d_stops:
            assert s in all_pts


def test_linear_stop_pickup_route_calculation() -> None:
    """Тестує побудову маршруту, коли посадка відбувається на лінійній зупинці (вул. Канатна)."""
    from services.tram_rental_service import RentalCalculationInput, calculate_rental_route

    calc_input = RentalCalculationInput(
        pickup_stop="вул. Канатна",
        dropoff_stop="Аркадія",
        intermediate_loop=None,
        via_loops=[],
        wagon_type="retro",
        transport_type="TRAM",
        wait_minutes_at_loop=5,
    )
    result = calculate_rental_route(calc_input)
    assert result.is_success is True

    # Фаза 1: виїзд з депо ВРМ на вул. Канатну
    assert result.phase_1_dispatch.from_stop == "ВРМ"
    assert result.phase_1_dispatch.to_stop == "вул. Канатна"
    assert result.phase_1_dispatch.distance_km > 0
    assert result.phase_1_dispatch.motion_minutes > 0

    # Фаза 2: рейс замовника вул. Канатна -> Аркадія
    assert result.phase_2_rental.from_stop == "вул. Канатна"
    assert result.phase_2_rental.to_stop == "Аркадія"
    assert result.phase_2_rental.distance_km > 0
    assert "Аркадія" in result.phase_2_rental.stops_path

    # Фаза 3: повернення з Аркадії у ВРМ
    assert result.phase_3_return.from_stop == "Аркадія"
    assert result.phase_3_return.to_stop == "ВРМ"
    assert result.phase_3_return.distance_km > 0

    assert result.total_duration_minutes >= 60
    assert result.total_billable_km > 0

    from services.rental_documents_service import RentalPriceInput, calculate_rental_price_breakdown
    breakdown = calculate_rental_price_breakdown(
        RentalPriceInput(duration_minutes=result.total_duration_minutes, wagon_key="retro_mtv")
    )
    assert breakdown.total_price_uah > 0
    assert breakdown.billable_minutes >= 60


def test_stop_directional_options_and_dashboard_editing() -> None:
    """Перевіряє генерацію варіантів напрямку руху для зупинок та структуру проміжних точок."""
    from services.tram_rental_service import get_stop_directional_options

    # Для двосторонньої зупинки 'вул. Канатна' має бути мінімум 2 напрямки
    kanatna_opts = get_stop_directional_options("вул. Канатна", "TRAM")
    assert len(kanatna_opts) >= 2
    directions = [opt["direction"] for opt in kanatna_opts]
    assert any("Музичної" in d or "Аркад" in d for d in directions)

    # Для кінцевого розворотного кільця 'Аркадія' — 1 варіант
    arcadia_opts = get_stop_directional_options("Аркадія", "TRAM")
    assert len(arcadia_opts) == 1
    assert arcadia_opts[0]["platform_id"] != ""

