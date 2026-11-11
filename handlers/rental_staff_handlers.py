"""
Обробники оперативного штабу КП «Одесміськелектротранс» для модуля оренди
трамваїв та тролейбусів:
- Рольова модель (RBAC) для 6 підрозділів (Служба руху, Юрвідділ, ВУПтаП, Бухгалтерія, ТД, ТрД);
- Двоетапний захист від випадкового натискання (2-step confirmation протягом 10 сек);
- Додавання вільних часових слотів у динамічний пул дати;
- Призначення бортового номера та водія з автоматичною видачею посадкового талона;
- Пересилання коментарів співробітників (Reply на картку з префіксом 'Коментар:') клієнту;
- Команди /chatid, /set_rental_chat, /add_rental_role для швидкого підключення чату;
- Автоматичний контроль 36-годинного тайм-ауту підписання паперових договорів.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config.settings import (
    RENTAL_ALLOWED_USER_IDS,
    RENTAL_IBAN_ACCOUNT,
    RENTAL_IBAN_EDRPOU,
    RENTAL_PAPER_LOCK_HOURS,
    RENTAL_PUBLIC_ENABLED,
    RENTAL_STAFF_CHAT_ID,
    RENTAL_STAFF_ROLES,
    VALENTIN_ADMIN_ID,
)
from database.db import Database, RentalOrder
from services.rental_documents_service import generate_rental_boarding_pass_pdf
from utils.logger import logger

db = Database()

STAFF_CONFIG_FILE = Path(__file__).resolve().parent.parent / "database" / "rental_staff_config.json"

ROLE_TITLES_UA: Dict[str, str] = {
    "traffic_service": "🚦 Служба руху (ВУПтаП)",
    "legal_dept": "⚖️ Юридичний відділ",
    "vuptap_dept": "🛡️ ВУПтаП (Безпека руху)",
    "accounting_dept": "💳 Бухгалтерія",
    "depot_tram": "🚋 Трамвайне депо / ВРМ",
    "depot_trolley": "🚎 Тролейбусне депо",
}

TOPIC_KEYS: List[str] = ["vuptap", "depot", "accounting", "legal", "analytics"]

TOPIC_TITLES_UA: Dict[str, str] = {
    "vuptap": "🚦 Адміністратор (ВУПтаП)",
    "depot": "🚋 ДЕПО та ВРМ",
    "accounting": "💳 Бухгалтерія",
    "legal": "⚖️ Відділ правового супроводу господарської діяльності",
    "analytics": "📊 Аналітика дій працівників",
}

# Двоетапне підтвердження натискання: (user_id, order_id, action_key) -> timestamp
_PENDING_CONFIRMATIONS: Dict[Tuple[int, int, str], float] = {}

# Очікування текстового вводу від співробітника: (chat_id, user_id) -> {"mode": "slots"|"depot"|"depot_add_slot", ...}
_PENDING_STAFF_INPUT: Dict[Tuple[int, int], Dict[str, Any]] = {}


def is_rental_access_allowed(user_id: int) -> bool:
    """
    Перевіряє, чи має користувач доступ до нового розділу оренди.
    Поки RENTAL_PUBLIC_ENABLED = False, розділ бачать лише авторизовані користувачі (RENTAL_ALLOWED_USER_IDS).
    """
    if RENTAL_PUBLIC_ENABLED:
        return True
    return int(user_id) in RENTAL_ALLOWED_USER_IDS or int(user_id) == VALENTIN_ADMIN_ID


def _load_runtime_staff_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "staff_chat_id": RENTAL_STAFF_CHAT_ID,
        "roles": {},
        "topics": {k: None for k in TOPIC_KEYS},
    }
    if STAFF_CONFIG_FILE.exists():
        try:
            with open(STAFF_CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    cfg.update(loaded)
                    if "topics" not in cfg or not isinstance(cfg["topics"], dict):
                        cfg["topics"] = {k: None for k in TOPIC_KEYS}
                    else:
                        for k in TOPIC_KEYS:
                            cfg["topics"].setdefault(k, None)
                    return cfg
        except Exception as exc:
            logger.warning(f"Не вдалося прочитати {STAFF_CONFIG_FILE}: {exc}")
    return cfg


def _save_runtime_staff_config(cfg: Dict[str, Any]) -> None:
    try:
        STAFF_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STAFF_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.error(f"Помилка збереження {STAFF_CONFIG_FILE}: {exc}")


def get_active_staff_chat_id() -> int:
    """
    Повертає ID штабної групи. Якщо група ще не прив'язана (0),
    безпечно повертає особистий ID Валентина (830196453) для тестування.
    """
    cfg = _load_runtime_staff_config()
    chat_id = int(cfg.get("staff_chat_id") or RENTAL_STAFF_CHAT_ID or 0)
    if chat_id != 0:
        return chat_id
    return VALENTIN_ADMIN_ID


def get_staff_topic_thread_id(topic_key: str) -> Optional[int]:
    """Повертає збережений message_thread_id для відповідної теми штабу."""
    cfg = _load_runtime_staff_config()
    val = cfg.get("topics", {}).get(topic_key)
    return int(val) if val is not None else None


async def send_to_staff_topic(
    context: ContextTypes.DEFAULT_TYPE,
    topic_key: str,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    document: Optional[Any] = None,
    filename: Optional[str] = None,
    caption: Optional[str] = None,
) -> Optional[int]:
    """
    Надсилає повідомлення або документ суворо у закріплену тему (forum topic)
    оперативного штабу КП «ОМЕТ» за ключем теми:
    - vuptap (Адміністратор ВУПтаП — Валентин)
    - depot (ДЕПО та ВРМ)
    - accounting (Бухгалтерія)
    - legal (Відділ правового супроводу...)
    - analytics (Аналітика дій працівників)
    Якщо тема ще не прив'язана через /bind_topic, надсилає у базовий чат штабу або особисто Валентину.
    """
    cfg = _load_runtime_staff_config()
    chat_id = get_active_staff_chat_id()
    thread_id = cfg.get("topics", {}).get(topic_key)

    kwargs: Dict[str, Any] = {
        "chat_id": chat_id,
        "parse_mode": ParseMode.HTML,
    }
    if thread_id is not None:
        kwargs["message_thread_id"] = int(thread_id)

    try:
        if document is not None:
            kwargs["document"] = document
            if filename:
                kwargs["filename"] = filename
            if caption:
                kwargs["caption"] = caption
            if reply_markup:
                kwargs["reply_markup"] = reply_markup
            sent = await context.bot.send_document(**kwargs)
            return sent.message_id
        else:
            kwargs["text"] = text
            if reply_markup:
                kwargs["reply_markup"] = reply_markup
            sent = await context.bot.send_message(**kwargs)
            return sent.message_id
    except Exception as exc:
        logger.error(f"Помилка відправки у тему '{topic_key}' (chat: {chat_id}, thread: {thread_id}): {exc}")
        return None


def has_staff_role(user_id: int, role_key: str, chat_id: Optional[int] = None) -> bool:
    """Перевіряє наявність ролі у співробітника. Валентин та учасники закритої штабної групи мають доступ."""
    uid = int(user_id)
    if uid == VALENTIN_ADMIN_ID or uid in RENTAL_ALLOWED_USER_IDS:
        return True
    base_ids = RENTAL_STAFF_ROLES.get(role_key, [])
    if uid in base_ids:
        return True
    cfg = _load_runtime_staff_config()
    extra_ids = [int(x) for x in cfg.get("roles", {}).get(role_key, [])]
    if uid in extra_ids:
        return True
    if chat_id is not None and int(chat_id) == get_active_staff_chat_id() and not extra_ids:
        return True
    return False


def check_two_step_confirmation(user_id: int, order_id: int, action_key: str, window_sec: float = 10.0) -> bool:
    """
    Реалізує двоетапне підтвердження (захист від випадкового натискання у спільному чаті).
    Перший клік повертає False і реєструє намір на 10 секунд; повторний клік повертає True.
    """
    now_ts = time.monotonic()
    key = (int(user_id), int(order_id), action_key)
    prev_ts = _PENDING_CONFIRMATIONS.get(key)
    if prev_ts is not None and (now_ts - prev_ts) <= window_sec:
        del _PENDING_CONFIRMATIONS[key]
        return True
    _PENDING_CONFIRMATIONS[key] = now_ts
    return False


# ================= ФОРМАТУВАННЯ ЖИВОЇ КАРТКИ ЗАМОВЛЕННЯ ТА ЖУРНАЛУ ДІЙ =================

STATUS_LABELS_UA: Dict[str, str] = {
    "pending_slots": "⏳ Очікує вільних часових слотів від Служби руху",
    "awaiting_slot_choice": "🕒 Слоти надано — клієнт обирає час",
    "awaiting_signature": "✍️ Очікує підписання договору клієнтом (контроль 36 год)",
    "signed_uploaded": "📄 Підписаний договір завантажено (перевірка Юрвідділу та оплати)",
    "revision_requested": "⚠️ Повернуто Юрвідділом на доопрацювання (правки)",
    "legal_approved": "⚖️ Договір погоджено Юрвідділом — очікує підтвердження IBAN",
    "paid_confirmed": "💳 Оплату IBAN підтверджено — очікує призначення вагона та водія в депо",
    "vehicle_assigned": "✅ Вагон та водія призначено (посадковий талон видано)",
    "completed": "🏁 Рейс успішно виконано",
    "expired_36h": "⌛ Скасовано автоматично (перевищено ліміт 36 год)",
    "cancelled": "🚫 Скасовано",
}


def _format_safety_client_stamp(order: RentalOrder) -> str:
    """Повертає штамп електронного ознайомлення клієнта з правилами пожежної та технічної безпеки."""
    safety_dt = getattr(order, "safety_accepted_at", None)
    if safety_dt:
        return f"✅ Прийнято клієнтом {safety_dt.strftime('%d.%m.%Y о %H:%M')}"
    return "✅ Прийнято електронно під час оформлення"


async def format_vuptap_summary_card_text(order: RentalOrder) -> str:
    """Формує Зведену картку замовлення (Summary Card) для Валентина у темі 'Адміністратор (ВУПтаП)'."""
    logs = await db.get_rental_audit_logs(order.id, limit=8)
    via_loops: List[str] = []
    try:
        via_loops = json.loads(order.via_loops_json or "[]")
    except Exception:
        via_loops = []

    via_str = " ➡️ ".join(via_loops) if via_loops else "прямий рейс"
    route_chain = f"{order.pickup_stop} ➡️ [{via_str}] ➡️ {order.dropoff_stop}"

    scenario_str = (
        "📱 Електронний (КЕП / Дія.Підпис .p7s)"
        if order.signing_scenario == "kep"
        else f"🏢 Паперовий в Управлінні КП (вул. Водопровідна, 1 — ліміт {RENTAL_PAPER_LOCK_HOURS} год)"
    )

    deadline_str = "—"
    if order.slot_lock_expires_at:
        deadline_str = order.slot_lock_expires_at.strftime("%d.%m.%Y %H:%M")

    traffic_mark = f"✅ {order.traffic_approved_by}" if order.traffic_approved_by else "⏳ очікує"
    vuptap_mark = (
        f"✅ {order.vuptap_approved_by} (ПБ, вогнегасники, інструктаж ОК)"
        if order.vuptap_approved_by
        else "⏳ очікує перевірки ПБ та інструктажу"
    )
    if order.status == "revision_requested":
        legal_mark = "⚠️ Повернуто замовнику на доопрацювання (правки)"
    elif order.legal_approved_by:
        legal_mark = f"✅ {order.legal_approved_by}"
    else:
        legal_mark = "⏳ очікує"
    acc_mark = f"✅ {order.accounting_approved_by}" if order.accounting_approved_by else "⏳ очікує"
    if order.assigned_board_number:
        depot_mark = (
            f"✅ Борт №{order.assigned_board_number}, водій {order.assigned_driver_name or '—'} "
            f"({order.assigned_driver_phone or '—'})"
        )
    else:
        depot_mark = "⏳ очікує (після договору та оплати)"

    vat_val = round(order.total_price_uah / 6.0, 2)
    without_vat = round(order.total_price_uah - vat_val, 2)
    cust_type_label = {
        "individual": "🚶 Фізособа",
        "fop": "💼 ФОП",
        "legal_entity": "🏢 Юрособа",
    }.get(getattr(order, "customer_type", "individual") or "individual", "🚶 Фізособа")
    safety_stamp = _format_safety_client_stamp(order)

    logs_block = ""
    if logs:
        log_items = []
        for l in logs[:6]:
            t_str = l.created_at.strftime("%H:%M") if l.created_at else ""
            log_items.append(f"• <i>{t_str}</i> <b>{l.actor_role}</b>: {l.details}")
        logs_block = "━━━━━━━━━━━━━━━━━━━━\n📜 <b>ДЕТАЛІЗОВАНИЙ ЖУРНАЛ ЗАМОВЛЕННЯ (AUDIT TRAIL):</b>\n" + "\n".join(log_items) + "\n"

    return (
        f"🚋 <b>ЗВЕДЕНА КАРТКА ЗАМОВЛЕННЯ № {order.contract_number}</b>\n"
        f"🆔 Код: <code>{order.order_uid}</code> | Статус: <b>{STATUS_LABELS_UA.get(order.status, order.status)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Замовник ({cust_type_label}):</b> {order.user_full_name}\n"
        f"📞 <b>Телефон:</b> <code>{order.user_phone}</code> | <b>РНОКПП/ЄДРПОУ:</b> <code>{order.user_tax_id or '—'}</code>\n"
        f"📅 <b>Дата та час подачі:</b> <b>{order.rental_date}</b> о <b>{order.rental_time_slot or 'ОЧІКУЄ СЛОТУ В ДЕПО'}</b>\n"
        f"⏳ <b>Контроль броні слоту:</b> до <b>{deadline_str}</b>\n"
        f"📝 <b>Формат договору:</b> {scenario_str}\n"
        f"🔥 <b>Правила ПБ та експлуатації:</b> {safety_stamp}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🚊 <b>Рухомий склад:</b> <b>{order.wagon_type}</b> (Депо: <b>{order.depot_code}</b>)\n"
        f"🗺️ <b>Маршрут:</b> {route_chain}\n"
        f"📏 <b>Телеметрія:</b> <b>{order.total_distance_km:.2f} км</b> | <b>{order.total_duration_min} хв</b>\n"
        f"💰 <b>Сума за договором:</b> <b>{order.total_price_uah:,.2f} грн</b> "
        f"(без ПДВ: {without_vat:,.2f} грн, ПДВ 20%: {vat_val:,.2f} грн)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ <b>СТАТУСИ ПОГОДЖЕНЬ ПІДРОЗДІЛІВ КП «ОМЕТ»:</b>\n"
        f"1️⃣ 🚦 ВУПтаП (Графік руху): {traffic_mark}\n"
        f"2️⃣ 🔥 ВУПтаП / Депо (Пожежна та тех. безпека): {vuptap_mark}\n"
        f"3️⃣ ⚖️ Юридичний відділ: {legal_mark}\n"
        f"4️⃣ 💳 Бухгалтерія (IBAN): {acc_mark}\n"
        f"5️⃣ 🚋 Депо ({order.depot_code}): {depot_mark}\n"
        f"{logs_block}"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 <i>Використовуйте кнопки нижче для швидкого коментаря клієнту або службової примітки.</i>"
    )


format_staff_order_card_text = format_vuptap_summary_card_text


def build_vuptap_order_keyboard(order: RentalOrder) -> InlineKeyboardMarkup:
    """Клавіатура для Валентина (Адміністратор ВУПтаП)."""
    oid = order.id
    rows: List[List[InlineKeyboardButton]] = []
    if order.status not in ("cancelled", "expired_36h", "completed"):
        row1: List[InlineKeyboardButton] = []
        if not order.traffic_approved_by:
            row1.append(InlineKeyboardButton("🚦 Погодити графік", callback_data=f"rental_staff:traffic_ok:{oid}"))
        if not order.vuptap_approved_by:
            row1.append(InlineKeyboardButton("🔥 ПБ та інструктаж ОК", callback_data=f"rental_staff:vuptap_ok:{oid}"))
        if row1:
            rows.append(row1)

        rows.append([
            InlineKeyboardButton("💬 Коментар клієнту", callback_data=f"rental_staff:comment_client:{oid}:vuptap"),
            InlineKeyboardButton("📌 Примітка штабу", callback_data=f"rental_staff:comment_internal:{oid}:vuptap"),
        ])

        rows.append([
            InlineKeyboardButton("🏁 Рейс виконано", callback_data=f"rental_staff:complete:{oid}"),
            InlineKeyboardButton("🚫 Скасувати", callback_data=f"rental_staff:cancel:{oid}"),
        ])
    return InlineKeyboardMarkup(rows)


build_staff_order_keyboard = build_vuptap_order_keyboard


async def format_legal_card_text(order: RentalOrder) -> str:
    """Формує картку договору для теми 'Відділ правового супроводу господарської діяльності'."""
    cust_type = getattr(order, "customer_type", "individual") or "individual"
    cust_type_label = {
        "individual": "🚶 Фізична особа",
        "fop": "💼 ФОП",
        "legal_entity": "🏢 Юридична особа",
    }.get(cust_type, "🚶 Фізична особа")
    scenario_str = (
        "📱 Електронний (КЕП / Дія.Підпис .p7s)"
        if order.signing_scenario == "kep"
        else "🏢 Паперовий в Управлінні КП (вул. Водопровідна, 1 — ліміт 36 год)"
    )
    deadline_str = order.slot_lock_expires_at.strftime("%d.%m.%Y %H:%M") if order.slot_lock_expires_at else "—"
    status_doc = f"✅ Завантажено ({order.signed_file_name or 'файл'})" if order.signed_file_id else "⏳ Очікується від клієнта"
    if order.status == "revision_requested":
        approval_str = "⚠️ Повернуто замовнику на доопрацювання (очікує виправлення)"
    elif order.legal_approved_by:
        approval_str = f"✅ Погоджено ({order.legal_approved_by})"
    else:
        approval_str = "⏳ Очікує правової перевірки"

    req_lines = [
        f"• <b>ПІБ / Назва:</b> {order.company_name or order.user_full_name}",
        f"• <b>РНОКПП / ЄДРПОУ:</b> <code>{order.user_tax_id or '—'}</code>",
    ]
    if getattr(order, "user_passport", None):
        req_lines.append(f"• <b>Паспорт / ID-картка:</b> <code>{order.user_passport}</code>")
    if getattr(order, "user_address", None):
        req_lines.append(f"• <b>Адреса / Реквізити:</b> {order.user_address}")
    if getattr(order, "signer_name", None):
        req_lines.append(f"• <b>Підписант / Виписка ЄДР:</b> {order.signer_name}")
    req_block = "\n".join(req_lines)

    return (
        f"⚖️ <b>ЮРИДИЧНИЙ ВІДДІЛ: ДОГОВІР ОРЕНДИ № {order.contract_number}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Статус замовника:</b> {cust_type_label}\n"
        f"📞 <b>Телефон:</b> <code>{order.user_phone}</code>\n"
        f"📋 <b>Реквізити у договорі:</b>\n{req_block}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>Формат підписання:</b> {scenario_str}\n"
        f"🔥 <b>Акцепт правил ПБ:</b> {_format_safety_client_stamp(order)}\n"
        f"⏳ <b>Контроль броні (36 год):</b> до <b>{deadline_str}</b>\n"
        f"📁 <b>Підписаний примірник клієнта:</b> {status_doc}\n"
        f"⚖️ <b>Висновок Юрвідділу:</b> <b>{approval_str}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>Ви можете погодити договір, повернути його на правки клієнту або надіслати коментар кнопками нижче.</i>"
    )


def build_legal_order_keyboard(order: RentalOrder) -> InlineKeyboardMarkup:
    """Клавіатура Юридичного відділу."""
    oid = order.id
    rows: List[List[InlineKeyboardButton]] = []
    if order.status not in ("cancelled", "expired_36h", "completed"):
        if not order.legal_approved_by:
            rows.append([InlineKeyboardButton("⚖️ Договір перевірено та погоджено", callback_data=f"rental_staff:legal_ok:{oid}")])
            if order.signing_scenario == "paper":
                rows.append([InlineKeyboardButton("✍️ Підписано паперово (Водопровідна, 1)", callback_data=f"rental_staff:legal_ok:{oid}")])
            rows.append([InlineKeyboardButton("⚠️ Повернути на правки клієнту", callback_data=f"rental_staff:legal_revision:{oid}")])
        else:
            rows.append([
                InlineKeyboardButton("✅ Договір погоджено Юрвідділом", callback_data=f"rental_staff:legal_ok:{oid}"),
                InlineKeyboardButton("⚠️ Повернути на правки", callback_data=f"rental_staff:legal_revision:{oid}"),
            ])
        rows.append([
            InlineKeyboardButton("💬 Коментар клієнту", callback_data=f"rental_staff:comment_client:{oid}:legal"),
            InlineKeyboardButton("📌 Примітка штабу", callback_data=f"rental_staff:comment_internal:{oid}:legal"),
        ])
    return InlineKeyboardMarkup(rows)


async def format_accounting_card_text(order: RentalOrder) -> str:
    """Формує картку фінансового контролю для теми 'Бухгалтерія'."""
    from services.rental_documents_service import format_money_ua, build_nbu_iban_payment_purpose
    total_val = float(order.total_price_uah or 0.0)
    vat_val = round(total_val / 6.0, 2)
    without_vat = round(total_val - vat_val, 2)
    contract_d = order.created_at.strftime("%d.%m.%Y") if order.created_at else datetime.datetime.now().strftime("%d.%m.%Y")
    purpose = build_nbu_iban_payment_purpose(order.contract_number, contract_d)
    payment_status = f"✅ Зараховано ({order.accounting_approved_by})" if order.accounting_approved_by else "⏳ Очікує підтвердження виписки"
    receipt_doc = "✅ Квитанцію завантажено клієнтом" if order.payment_file_id else "⏳ Очікує оплати замовником"

    return (
        f"💳 <b>БУХГАЛТЕРІЯ: РАХУНОК-ФАКТУРА IBAN (№ {order.contract_number})</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Платник:</b> {order.user_full_name} (РНОКПП/ЄДРПОУ: <code>{order.user_tax_id or '—'}</code>)\n"
        f"💰 <b>Загальна сума до сплати:</b> <b>{format_money_ua(total_val)} грн</b>\n"
        f"   • Сума без ПДВ: {format_money_ua(without_vat)} грн\n"
        f"   • ПДВ 20%: {format_money_ua(vat_val)} грн\n"
        f"🏛️ <b>Реквізити КП «ОМЕТ»:</b>\n"
        f"   • IBAN: <code>{RENTAL_IBAN_ACCOUNT}</code>\n"
        f"   • ЄДРПОУ: <code>{RENTAL_IBAN_EDRPOU}</code>\n"
        f"📝 <b>Призначення платежу:</b>\n<code>{purpose}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 <b>Квитанція замовника:</b> {receipt_doc}\n"
        f"💳 <b>Статус зарахування коштів:</b> <b>{payment_status}</b>"
    )


def build_accounting_order_keyboard(order: RentalOrder) -> InlineKeyboardMarkup:
    """Клавіатура Бухгалтерії."""
    oid = order.id
    rows: List[List[InlineKeyboardButton]] = []
    if order.status not in ("cancelled", "expired_36h", "completed"):
        if not order.accounting_approved_by:
            rows.append([InlineKeyboardButton("💳 Оплату IBAN зараховано (100%)", callback_data=f"rental_staff:acc_ok:{oid}")])
        else:
            rows.append([InlineKeyboardButton("✅ Оплату підтверджено Бухгалтерією", callback_data=f"rental_staff:acc_ok:{oid}")])
        rows.append([
            InlineKeyboardButton("💬 Коментар клієнту", callback_data=f"rental_staff:comment_client:{oid}:accounting"),
            InlineKeyboardButton("📌 Примітка штабу", callback_data=f"rental_staff:comment_internal:{oid}:accounting"),
        ])
    return InlineKeyboardMarkup(rows)


async def format_depot_card_text(order: RentalOrder) -> str:
    """Формує наряд на випуск вагона для теми 'ДЕПО та ВРМ'."""
    is_ready = bool(order.legal_approved_by and order.accounting_approved_by)
    status_header = "🟢 НАРЯД НА ВИПУСК ВАГОНА" if is_ready else "⏳ ПОПЕРЕДНЯ ЗАЯВКА НА ВИПУСК"
    assigned_info = (
        f"✅ Борт №{order.assigned_board_number}, водій: {order.assigned_driver_name} ({order.assigned_driver_phone})"
        if order.assigned_board_number
        else "⏳ Очікує призначення борта та водія"
    )
    fire_safety_status = (
        f"✅ Перевірено ({order.vuptap_approved_by}: вогнегасники ВП-5/ВВК-3,5, аптечка, башмаки, інструктаж водія)"
        if order.vuptap_approved_by
        else "⏳ Потребує перевірки вогнегасників, аптечки та цільового інструктажу перед виїздом"
    )
    return (
        f"🚋 <b>{status_header} (ДОГОВІР № {order.contract_number})</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🚊 <b>Рухомий склад:</b> <b>{order.wagon_type}</b> (База: <b>{order.depot_code}</b>)\n"
        f"📅 <b>Дата рейсу:</b> <b>{order.rental_date}</b> о <b>{order.rental_time_slot or 'час погоджується'}</b>\n"
        f"📍 <b>Початкова зупинка посадки:</b> <b>{order.pickup_stop}</b>\n"
        f"📍 <b>Кінцева зупинка маршруту:</b> {order.dropoff_stop}\n"
        f"⏱️ <b>Тривалість:</b> {order.total_duration_min} хв (подача: {order.duration_pull_out_min} хв, заїзд: {order.duration_pull_in_min} хв)\n"
        f"🛣️ <b>Пробіг за маршрутом:</b> {order.total_distance_km:.2f} км\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👨‍✈️ <b>Призначений екіпаж:</b> {assigned_info}\n"
        f"🔥 <b>Пожежна та тех. безпека (ПБ):</b> {fire_safety_status}\n"
        f"🛡️ <b>Акцепт ПБ замовником:</b> {_format_safety_client_stamp(order)}\n"
        f"📋 <b>Готовність:</b> Договір: {'✅' if order.legal_approved_by else '⏳'} | Оплата IBAN: {'✅' if order.accounting_approved_by else '⏳'}"
    )


def build_depot_order_keyboard(order: RentalOrder) -> InlineKeyboardMarkup:
    """Клавіатура ДЕПО та ВРМ."""
    oid = order.id
    rows: List[List[InlineKeyboardButton]] = []
    if order.status not in ("cancelled", "expired_36h", "completed"):
        if not order.assigned_board_number:
            rows.append([InlineKeyboardButton(f"🚋 Призначити вагон і водія ({order.depot_code})", callback_data=f"rental_staff:depot_assign:{oid}")])
        else:
            rows.append([InlineKeyboardButton(f"✏️ Змінити борт/водія (№{order.assigned_board_number})", callback_data=f"rental_staff:depot_assign:{oid}")])
        if not order.vuptap_approved_by:
            rows.append([InlineKeyboardButton("🔥 Підтвердити ПБ (вогнегасник, аптечка, інструктаж)", callback_data=f"rental_staff:vuptap_ok:{oid}")])
        rows.append([
            InlineKeyboardButton("💬 Коментар клієнту", callback_data=f"rental_staff:comment_client:{oid}:depot"),
            InlineKeyboardButton("📌 Примітка штабу", callback_data=f"rental_staff:comment_internal:{oid}:depot"),
        ])
    return InlineKeyboardMarkup(rows)


async def post_or_update_staff_order_card(
    context: ContextTypes.DEFAULT_TYPE,
    order_id: int,
) -> Optional[int]:
    """
    Публікує нову або оновлює існуючі профільні картки замовлення
    у 4 робочих темах оперативного штабу КП «ОМЕТ»:
    1. Адміністратор (ВУПтаП) — Зведена картка замовлення для Валентина;
    2. Відділ правового супроводу... — Картка договору та КЕП;
    3. Бухгалтерія — Картка рахунку та підтвердження оплати IBAN;
    4. ДЕПО та ВРМ — Наряд на випуск рухомого складу та водія.
    Якщо теми ще не прив'язані, безпечно надсилає у базовий чат або особисто Валентину.
    """
    order = await db.get_rental_order(order_id)
    if not order:
        return None

    cfg = _load_runtime_staff_config()
    topics_map = cfg.get("topics", {})
    target_chat_id = order.staff_chat_id or get_active_staff_chat_id()

    topic_msgs: Dict[str, int] = {}
    try:
        topic_msgs = json.loads(getattr(order, "staff_topic_messages_json", "") or "{}")
    except Exception:
        topic_msgs = {}

    # 1. ТЕМА «Адміністратор (ВУПтаП)»: Зведена картка (Валентин)
    vuptap_text = await format_vuptap_summary_card_text(order)
    vuptap_markup = build_vuptap_order_keyboard(order)
    vuptap_thread = topics_map.get("vuptap")
    vuptap_msg_id = topic_msgs.get("vuptap") or order.staff_chat_message_id

    updated_vuptap_id: Optional[int] = None
    if vuptap_msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=target_chat_id,
                message_id=vuptap_msg_id,
                text=vuptap_text,
                reply_markup=vuptap_markup,
                parse_mode=ParseMode.HTML,
            )
            updated_vuptap_id = vuptap_msg_id
        except Exception as edit_err:
            if "Message is not modified" in str(edit_err):
                updated_vuptap_id = vuptap_msg_id
            else:
                updated_vuptap_id = None

    if not updated_vuptap_id:
        send_kwargs: Dict[str, Any] = {
            "chat_id": target_chat_id,
            "text": vuptap_text,
            "reply_markup": vuptap_markup,
            "parse_mode": ParseMode.HTML,
        }
        if vuptap_thread is not None:
            send_kwargs["message_thread_id"] = vuptap_thread
        try:
            sent_v = await context.bot.send_message(**send_kwargs)
            updated_vuptap_id = sent_v.message_id
        except Exception as err:
            logger.error(f"Помилка відправки картки ВУПтаП #{order.id}: {err}")

    if updated_vuptap_id:
        topic_msgs["vuptap"] = updated_vuptap_id

    # 2. ТЕМА «Відділ правового супроводу господарської діяльності» (Юристи)
    legal_thread = topics_map.get("legal")
    if legal_thread is not None:
        legal_text = await format_legal_card_text(order)
        legal_markup = build_legal_order_keyboard(order)
        legal_msg_id = topic_msgs.get("legal")
        if legal_msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=target_chat_id,
                    message_id=legal_msg_id,
                    text=legal_text,
                    reply_markup=legal_markup,
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
        else:
            try:
                sent_l = await context.bot.send_message(
                    chat_id=target_chat_id,
                    message_thread_id=legal_thread,
                    text=legal_text,
                    reply_markup=legal_markup,
                    parse_mode=ParseMode.HTML,
                )
                topic_msgs["legal"] = sent_l.message_id
            except Exception as err:
                logger.error(f"Помилка відправки картки Юрвідділу #{order.id}: {err}")

    # 3. ТЕМА «Бухгалтерія» (Оплата IBAN)
    acc_thread = topics_map.get("accounting")
    if acc_thread is not None:
        acc_text = await format_accounting_card_text(order)
        acc_markup = build_accounting_order_keyboard(order)
        acc_msg_id = topic_msgs.get("accounting")
        if acc_msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=target_chat_id,
                    message_id=acc_msg_id,
                    text=acc_text,
                    reply_markup=acc_markup,
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
        else:
            try:
                sent_a = await context.bot.send_message(
                    chat_id=target_chat_id,
                    message_thread_id=acc_thread,
                    text=acc_text,
                    reply_markup=acc_markup,
                    parse_mode=ParseMode.HTML,
                )
                topic_msgs["accounting"] = sent_a.message_id
            except Exception as err:
                logger.error(f"Помилка відправки картки Бухгалтерії #{order.id}: {err}")

    # 4. ТЕМА «ДЕПО та ВРМ» (Наряд на випуск вагона)
    depot_thread = topics_map.get("depot")
    if depot_thread is not None:
        depot_text = await format_depot_card_text(order)
        depot_markup = build_depot_order_keyboard(order)
        depot_msg_id = topic_msgs.get("depot")
        if depot_msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=target_chat_id,
                    message_id=depot_msg_id,
                    text=depot_text,
                    reply_markup=depot_markup,
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
        else:
            try:
                sent_d = await context.bot.send_message(
                    chat_id=target_chat_id,
                    message_thread_id=depot_thread,
                    text=depot_text,
                    reply_markup=depot_markup,
                    parse_mode=ParseMode.HTML,
                )
                topic_msgs["depot"] = sent_d.message_id
            except Exception as err:
                logger.error(f"Помилка відправки наряду в Депо #{order.id}: {err}")

    await db.update_rental_order_fields(
        order.id,
        {
            "staff_chat_id": target_chat_id,
            "staff_chat_message_id": updated_vuptap_id or order.staff_chat_message_id,
            "staff_topic_messages_json": json.dumps(topic_msgs),
        },
    )
    return updated_vuptap_id or order.staff_chat_message_id


# ================= ОБРОБНИК НАТИСКАНЬ КНОПОК ПІДРОЗДІЛІВ У ШТАБНОМУ ЧАТІ =================

ACTION_REQUIRED_ROLE: Dict[str, Tuple[str, str]] = {
    "traffic_ok": ("traffic_service", "Служба руху"),
    "add_slots": ("traffic_service", "Служба руху"),
    "legal_ok": ("legal_dept", "Юридичний відділ"),
    "legal_revision": ("legal_dept", "Юридичний відділ"),
    "vuptap_ok": ("vuptap_dept", "ВУПтаП / Депо (ПБ)"),
    "acc_ok": ("accounting_dept", "Бухгалтерія"),
    "depot_assign": ("depot_tram", "Депо"),
    "comment_client": ("traffic_service", "Штаб КП ОМЕТ"),
    "comment_internal": ("traffic_service", "Штаб КП ОМЕТ"),
    "complete": ("traffic_service", "Служба руху"),
    "cancel": ("traffic_service", "Служба руху"),
}

PROMPT_ONLY_ACTIONS = ("depot_assign", "add_slots", "legal_revision", "comment_client", "comment_internal")


def _resolve_department_label(topic_key: Optional[str], thread_id: Optional[int] = None) -> str:
    """Визначає назву підрозділу КП «ОМЕТ» за ключем теми або ID потоку (thread_id)."""
    if topic_key and topic_key in TOPIC_TITLES_UA:
        return TOPIC_TITLES_UA[topic_key]
    if thread_id is not None:
        cfg = _load_runtime_staff_config()
        topics_map = cfg.get("topics", {})
        for k, tid in topics_map.items():
            if tid is not None and int(tid) == int(thread_id):
                return TOPIC_TITLES_UA.get(k, "Оперативний штаб КП «ОМЕТ»")
    return "Оперативний штаб КП «ОМЕТ»"


async def handle_rental_staff_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє всі інлайн-кнопки `rental_staff:<action>:<order_id>` у штабному чаті."""
    query = update.callback_query
    if not query or not query.data:
        return

    parts = query.data.split(":")
    if len(parts) < 3:
        await query.answer()
        return

    action = parts[1]
    order_id = int(parts[2])
    topic_key_arg = parts[3] if len(parts) > 3 else None
    user = update.effective_user
    user_id = user.id
    actor_name = user.full_name or user.username or str(user_id)

    order = await db.get_rental_order(order_id)
    if not order:
        await query.answer("❌ Замовлення не знайдено в базі даних.", show_alert=True)
        return

    # 1. Перевірка ролі підрозділу (RBAC)
    chat_id_for_rbac = update.effective_chat.id if update.effective_chat else None
    req_role_key, role_label = ACTION_REQUIRED_ROLE.get(action, ("traffic_service", "Штаб"))
    if action == "depot_assign":
        if order.transport_type == "TROLLEYBUS":
            allowed = has_staff_role(user_id, "depot_trolley", chat_id_for_rbac) or has_staff_role(user_id, "depot_tram", chat_id_for_rbac)
            role_label = "Тролейбусне депо"
        else:
            allowed = has_staff_role(user_id, "depot_tram", chat_id_for_rbac)
            role_label = f"Депо {order.depot_code}"
    elif action == "vuptap_ok":
        allowed = (
            has_staff_role(user_id, "vuptap_dept", chat_id_for_rbac)
            or has_staff_role(user_id, "depot_tram", chat_id_for_rbac)
            or has_staff_role(user_id, "traffic_service", chat_id_for_rbac)
        )
    elif action in ("comment_client", "comment_internal"):
        allowed = is_rental_staff_member(user_id, chat_id_for_rbac)
    else:
        allowed = has_staff_role(user_id, req_role_key, chat_id_for_rbac)

    if not allowed:
        await query.answer(
            f"⛔ Доступ обмежено! Ця кнопка призначена виключно для підрозділу «{role_label}».",
            show_alert=True,
        )
        return

    # 2. Двоетапний захист від випадкового натискання (протягом 10 секунд) — не блокуємо для кнопок відкриття діалогу вводу
    if action not in PROMPT_ONLY_ACTIONS and not check_two_step_confirmation(user_id, order_id, action):
        await query.answer(
            f"⚠️ Підтвердження дії ({role_label}):\n"
            f"Натисніть цю саму кнопку ЩЕ РАЗ протягом 10 секунд, щоб підтвердити дію за договором №{order.contract_number}.",
            show_alert=True,
        )
        return

    now_dt = datetime.datetime.now()
    thread_id = getattr(query.message, "message_thread_id", None) if query.message else None

    # 3. Виконання підтвердженої дії
    if action == "traffic_ok":
        await db.update_rental_order_fields(
            order.id,
            {
                "traffic_approved_by": actor_name,
                "traffic_approved_at": now_dt,
            },
        )
        await db.add_rental_audit_log(
            order_id=order.id,
            actor_id=user_id,
            actor_name=actor_name,
            actor_role="🚦 Служба руху (ВУПтаП)",
            action="TRAFFIC_APPROVED",
            details=f"Погоджено маршрут та часовий слот {order.rental_date} ({order.rental_time_slot or 'за графіком'})",
        )
        await query.answer("✅ Служба руху погодила замовлення!")
        await post_or_update_staff_order_card(context, order.id)
        try:
            await context.bot.send_message(
                chat_id=order.user_id,
                text=(
                    f"🚦 <b>Служба руху КП «ОМЕТ» погодила Ваш маршрут та часовий слот!</b>\n"
                    f"Договір: <b>№ {order.contract_number}</b>\n"
                    f"Дата та час: <b>{order.rental_date} о {order.rental_time_slot or 'узгоджений час'}</b>."
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    if action == "add_slots":
        chat_id = update.effective_chat.id
        _PENDING_STAFF_INPUT[(chat_id, user_id)] = {
            "mode": "slots",
            "order_id": order.id,
            "rental_date": order.rental_date,
            "transport_type": order.transport_type,
        }
        await query.answer("Введіть вільні часові слоти у чат")
        prompt_kwargs: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": (
                f"🕒 <b>Додавання вільних слотів у пул на дату {order.rental_date}</b> (для Договору №{order.contract_number}):\n\n"
                f"Напишіть у відповідь вільні години подачі через кому (наприклад: <code>11:00, 14:00, 16:30</code>).\n"
                f"<i>Усі додані слоти збережуться в базі: коли перший клієнт обере один слот, решта залишаться доступними для наступних клієнтів!</i>"
            ),
            "parse_mode": ParseMode.HTML,
        }
        if thread_id is not None:
            prompt_kwargs["message_thread_id"] = thread_id
        await context.bot.send_message(**prompt_kwargs)
        return

    if action == "legal_ok":
        new_status = order.status
        if order.status in ("awaiting_signature", "signed_uploaded", "revision_requested"):
            new_status = "legal_approved"
        await db.update_rental_order_fields(
            order.id,
            {
                "legal_approved_by": actor_name,
                "legal_approved_at": now_dt,
                "status": new_status,
            },
        )
        await db.add_rental_audit_log(
            order_id=order.id,
            actor_id=user_id,
            actor_name=actor_name,
            actor_role="⚖️ Юридичний відділ",
            action="LEGAL_APPROVED",
            details=f"Договір №{order.contract_number} перевірено та погоджено Юридичним відділом",
        )
        await query.answer("✅ Юридичний відділ погодив договір!")
        await post_or_update_staff_order_card(context, order.id)
        try:
            await context.bot.send_message(
                chat_id=order.user_id,
                text=(
                    f"⚖️ <b>Відділ правового супроводу КП «ОМЕТ» підтвердив Ваш Договір № {order.contract_number}!</b>\n"
                    f"Будь ласка, переконайтеся, що оплату за реквізитами IBAN здійснено, та очікуйте підтвердження Бухгалтерії."
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    if action == "legal_revision":
        chat_id = update.effective_chat.id
        target_thread = thread_id if thread_id is not None else get_staff_topic_thread_id("legal")
        _PENDING_STAFF_INPUT[(chat_id, user_id)] = {
            "mode": "legal_revision",
            "order_id": order.id,
            "thread_id": target_thread,
        }
        await query.answer("Введіть зауваження Юрвідділу у чат теми")
        rev_kwargs: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": (
                f"⚠️ <b>Повернення Договору №{order.contract_number} на доопрацювання (правки):</b>\n\n"
                f"Напишіть одним повідомленням у цю тему перелік зауважень для замовника "
                f"(наприклад: <i>«Уточніть серію/номер паспорта або ЄДРПОУ, завантажте підписаний файл .p7s»</i>).\n\n"
                f"<i>Клієнт миттєво отримає Ваше зауваження разом із кнопками для виправлення реквізитів та повторного завантаження договору.</i>"
            ),
            "parse_mode": ParseMode.HTML,
        }
        if target_thread is not None:
            rev_kwargs["message_thread_id"] = target_thread
        await context.bot.send_message(**rev_kwargs)
        return

    if action in ("comment_client", "comment_internal"):
        chat_id = update.effective_chat.id
        dept_label = _resolve_department_label(topic_key_arg, thread_id)
        _PENDING_STAFF_INPUT[(chat_id, user_id)] = {
            "mode": action,
            "order_id": order.id,
            "topic_key": topic_key_arg or "vuptap",
            "dept_label": dept_label,
            "thread_id": thread_id,
        }
        if action == "comment_client":
            await query.answer("Напишіть повідомлення для клієнта у чат")
            prompt_txt = (
                f"💬 <b>Повідомлення клієнту від підрозділу «{dept_label}» (Договір №{order.contract_number}):</b>\n\n"
                f"Напишіть наступним повідомленням у цю тему текст, який потрібно передати замовнику (<b>{order.user_full_name}</b>)."
            )
        else:
            await query.answer("Напишіть службову примітку для штабу у чат")
            prompt_txt = (
                f"📌 <b>Внутрішня службова примітка від «{dept_label}» (Договір №{order.contract_number}):</b>\n\n"
                f"Напишіть наступним повідомленням службовий коментар. Він збережеться у Зведеній картці штабу (ВУПтаП) та журналі аудиту, "
                f"але <b>не буде надсилатися клієнту</b>."
            )
        c_kwargs: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": prompt_txt,
            "parse_mode": ParseMode.HTML,
        }
        if thread_id is not None:
            c_kwargs["message_thread_id"] = thread_id
        await context.bot.send_message(**c_kwargs)
        return

    if action == "vuptap_ok":
        await db.update_rental_order_fields(
            order.id,
            {
                "vuptap_approved_by": actor_name,
                "vuptap_approved_at": now_dt,
            },
        )
        await db.add_rental_audit_log(
            order_id=order.id,
            actor_id=user_id,
            actor_name=actor_name,
            actor_role="🔥 Пожежна та тех. безпека (ВУПтаП / Депо)",
            action="VUPTAP_APPROVED",
            details="Підтверджено пожежну та тех. безпеку (вогнегасник ВП-5/ВВК-3,5, аптечка, башмаки, цільовий інструктаж)",
        )
        await query.answer("✅ Пожежну безпеку та інструктаж підтверджено!")
        await post_or_update_staff_order_card(context, order.id)
        return

    if action == "acc_ok":
        await db.update_rental_order_fields(
            order.id,
            {
                "accounting_approved_by": actor_name,
                "accounting_approved_at": now_dt,
                "status": "paid_confirmed",
            },
        )
        await db.book_rental_slot_by_order(order.id)
        await db.add_rental_audit_log(
            order_id=order.id,
            actor_id=user_id,
            actor_name=actor_name,
            actor_role="💳 Бухгалтерія",
            action="PAYMENT_CONFIRMED",
            details=f"Підтверджено зарахування {order.total_price_uah:.2f} грн за реквізитами IBAN",
        )
        await query.answer("✅ Оплату IBAN підтверджено!")
        await post_or_update_staff_order_card(context, order.id)
        try:
            await context.bot.send_message(
                chat_id=order.user_id,
                text=(
                    f"💳 <b>Бухгалтерія КП «ОМЕТ» підтвердила зарахування оплати ({order.total_price_uah:.2f} грн) за Договором № {order.contract_number}!</b>\n\n"
                    f"Наряд передано у депо <b>{order.depot_code}</b> для призначення бортового номера та водія. "
                    f"Як тільки вагон буде призначено, Ви отримаєте електронний посадковий талон із QR-кодом."
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    if action == "depot_assign":
        chat_id = update.effective_chat.id
        target_depot_thread = thread_id if thread_id is not None else get_staff_topic_thread_id("depot")
        _PENDING_STAFF_INPUT[(chat_id, user_id)] = {
            "mode": "depot",
            "order_id": order.id,
        }
        await query.answer("Введіть бортовий номер та ПІБ водія у чат")
        depot_prompt_kwargs: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": (
                f"🚋 <b>Призначення рухомого складу та водія ({order.depot_code}) для Договору №{order.contract_number}:</b>\n\n"
                f"Надішліть одним повідомленням через кому:\n"
                f"<code>Бортовий №, ПІБ водія, Телефон водія</code>\n"
                f"Наприклад: <code>914, Коваленко Олександр Петрович, +380501112233</code>"
            ),
            "parse_mode": ParseMode.HTML,
        }
        if target_depot_thread is not None:
            depot_prompt_kwargs["message_thread_id"] = target_depot_thread
        await context.bot.send_message(**depot_prompt_kwargs)
        return

    if action == "complete":
        await db.update_rental_order_fields(order.id, {"status": "completed"})
        await db.add_rental_audit_log(
            order_id=order.id,
            actor_id=user_id,
            actor_name=actor_name,
            actor_role=role_label,
            action="COMPLETED",
            details="Орендний рейс успішно виконано",
        )
        await query.answer("🏁 Замовлення позначено як виконане!")
        await post_or_update_staff_order_card(context, order.id)
        try:
            await send_to_staff_topic(
                context,
                "vuptap",
                (
                    f"🏁 <b>Рейс успішно виконано!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Договір: <b>№ {order.contract_number}</b>\n"
                    f"Замовник: {order.user_full_name} ({order.user_phone})\n"
                    f"Вагон: <b>{order.wagon_type}</b> (борт №{order.assigned_board_number or '—'})\n"
                    f"Водій: <b>{order.assigned_driver_name or '—'}</b>\n"
                    f"Дата та час: <b>{order.rental_date} о {order.rental_time_slot or '—'}</b>\n"
                    f"Маршрут: {order.pickup_stop} ➡️ {order.dropoff_stop}\n"
                    f"Сума договору: <b>{float(order.total_price_uah or 0):.2f} грн</b>"
                ),
            )
        except Exception:
            pass
        return

    if action == "cancel":
        await db.update_rental_order_fields(order.id, {"status": "cancelled"})
        await db.release_rental_slot_by_order(order.id)
        await db.add_rental_audit_log(
            order_id=order.id,
            actor_id=user_id,
            actor_name=actor_name,
            actor_role=role_label,
            action="CANCELLED",
            details="Замовлення скасовано співробітником штабу, часовий слот повернуто у вільний пул",
        )
        await query.answer("🚫 Замовлення скасовано, слот звільнено.")
        await post_or_update_staff_order_card(context, order.id)
        try:
            await send_to_staff_topic(
                context,
                "vuptap",
                (
                    f"🚫 <b>Замовлення скасовано!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Договір: <b>№ {order.contract_number}</b>\n"
                    f"Замовник: {order.user_full_name} ({order.user_phone})\n"
                    f"Вагон: <b>{order.wagon_type}</b>\n"
                    f"Часовий слот ({order.rental_date} {order.rental_time_slot or ''}) звільнено та повернуто у вільний пул."
                ),
            )
        except Exception:
            pass
        try:
            await context.bot.send_message(
                chat_id=order.user_id,
                text=(
                    f"🚫 <b>Замовлення за Договором № {order.contract_number} було скасовано.</b>\n"
                    f"За додатковою інформацією звертайтеся до Інформаційного центру КП «ОМЕТ»."
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


# ================= ОБРОБНИК ТЕКСТОВИХ ПОВІДОМЛЕНЬ ТА КОМЕНТАРІВ У ШТАБНОМУ ЧАТІ =================

async def handle_staff_group_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Обробляє:
    1) Очікуваний ввід часових слотів ('12:00, 15:00') від Служби руху
    2) Очікуваний ввід бортового номера та водія ('914, Коваленко О.П., +380...') від Депо
    3) Зауваження та правки від Юридичного відділу ('legal_revision')
    4) Одноклікові коментарі клієнту ('comment_client') та внутрішні примітки штабу ('comment_internal')
    5) Reply на картку замовлення з префіксом 'Коментар: ...' або 'Інфо: ...' для клієнта.
    Повертає True, якщо повідомлення було оброблено.
    """
    msg = update.message
    if not msg or not update.effective_user or not update.effective_chat:
        return False
    raw_text = msg.text or getattr(msg, "caption", None) or ""
    if not raw_text and not getattr(msg, "document", None):
        return False

    chat_id = update.effective_chat.id
    user = update.effective_user
    user_id = user.id
    actor_name = user.full_name or user.username or str(user_id)
    text = raw_text.strip()

    # 1. Перевіряємо активний режим вводу (слоти, депо, правки юристів, коментарі служб)
    pending = _PENDING_STAFF_INPUT.get((chat_id, user_id))
    if pending:
        mode = pending.get("mode")

        if mode == "depot_add_slot":
            del _PENDING_STAFF_INPUT[(chat_id, user_id)]
            m = re.match(r"^(\d{2}\.\d{2}\.\d{4})[\s,]+(.+)$", text)
            if not m:
                await msg.reply_text(
                    "⚠️ Невірний формат. Введіть дату та години у форматі:\n"
                    "<code>15.05.2026 10:00, 14:00</code>",
                    parse_mode=ParseMode.HTML,
                )
                return True
            target_date = m.group(1).strip()
            raw_times = m.group(2).strip()
            valid_slots = [s.strip() for s in re.split(r"[,;\s]+", raw_times) if re.match(r"^\d{1,2}:\d{2}$", s.strip())]
            if not valid_slots:
                await msg.reply_text(
                    "⚠️ Не знайдено жодного коректного часу (формат ГГ:ХХ). Наприклад: <code>10:00, 14:00</code>.",
                    parse_mode=ParseMode.HTML,
                )
                return True
            added = await db.add_rental_slots(
                rental_date=target_date,
                slot_times=valid_slots,
                transport_type="retro_tram",
                added_by_id=user_id,
                added_by_name=actor_name,
            )
            await db.add_rental_audit_log(
                order_id=0,
                actor_id=user_id,
                actor_name=actor_name,
                actor_role="🚋 ДЕПО та ВРМ",
                action="SLOTS_ADDED",
                details=f"Депо додало {len(added)} вільних слотів на {target_date}: {', '.join(valid_slots)}",
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🚋 До пульта слотів Депо", callback_data="depot_slots:menu")]
            ])
            await msg.reply_text(
                f"✅ Успішно додано <b>{len(added)}</b> вільних слотів на <b>{target_date}</b>:\n"
                f"🕒 <b>{', '.join(valid_slots)}</b>\n\n"
                f"Клієнти тепер можуть обрати ці години під час оформлення оренди.",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
            return True

        order_id = int(pending["order_id"])
        order = await db.get_rental_order(order_id)
        del _PENDING_STAFF_INPUT[(chat_id, user_id)]

        if not order:
            await msg.reply_text("❌ Замовлення не знайдено.")
            return True

        if mode == "legal_revision":
            rev_text = text or "Надіслано відредагований файл договору від Юридичного відділу"
            await db.update_rental_order_fields(
                order.id,
                {
                    "status": "revision_requested",
                    "legal_approved_by": None,
                    "legal_approved_at": None,
                },
            )
            await db.add_rental_audit_log(
                order_id=order.id,
                actor_id=user_id,
                actor_name=actor_name,
                actor_role="⚖️ Юридичний відділ",
                action="LEGAL_REVISION_REQUESTED",
                details=f"Повернуто на доопрацювання: {rev_text}",
            )
            await post_or_update_staff_order_card(context, order.id)
            client_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Виправити реквізити та перегенерувати договір", callback_data=f"rental_fix_requisites:{order.id}")],
                [InlineKeyboardButton("📤 Завантажити виправлений договір (.p7s / скан)", callback_data=f"rental_upload_signed:{order.id}")],
                [InlineKeyboardButton("📂 Мої діючі договори", callback_data="rental_my_contracts")],
            ])
            try:
                if getattr(msg, "document", None):
                    await context.bot.send_document(
                        chat_id=order.user_id,
                        document=msg.document.file_id,
                        caption=f"📄 Відредагована редакція Договору № {order.contract_number} від Юридичного відділу КП «ОМЕТ»",
                        parse_mode=ParseMode.HTML,
                    )
                await context.bot.send_message(
                    chat_id=order.user_id,
                    text=(
                        f"⚠️ <b>Зауваження Відділу правового супроводу КП «ОМЕТ» за Договором № {order.contract_number}:</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"<i>«{rev_text}»</i>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"Будь ласка, скористайтеся кнопками нижче, щоб відкоригувати реквізити (система автоматично згенерує "
                        f"оновлений PDF-договір) або завантажити виправлений підписаний файл:"
                    ),
                    reply_markup=client_kb,
                    parse_mode=ParseMode.HTML,
                )
                await msg.reply_text(
                    f"✅ Договір <b>№{order.contract_number}</b> переведено у статус «На доопрацюванні».\n"
                    f"Зауваження та кнопки виправлення реквізитів надіслано замовнику.",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as err:
                await msg.reply_text(f"⚠️ Статус оновлено, але не вдалося доставити повідомлення клієнту: {err}")
            return True

        if mode == "comment_client":
            dept_label = pending.get("dept_label") or _resolve_department_label(pending.get("topic_key"), getattr(msg, "message_thread_id", None))
            await db.add_rental_audit_log(
                order_id=order.id,
                actor_id=user_id,
                actor_name=actor_name,
                actor_role=dept_label,
                action="STAFF_COMMENT_CLIENT",
                details=f"Повідомлення клієнту: {text}",
            )
            await post_or_update_staff_order_card(context, order.id)
            client_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📄 Переглянути договір №{order.contract_number}", callback_data=f"rental_contract_view:{order.id}")],
            ])
            try:
                await context.bot.send_message(
                    chat_id=order.user_id,
                    text=(
                        f"💬 <b>Офіційне повідомлення від підрозділу «{dept_label}» КП «ОМЕТ»</b>\n"
                        f"Щодо Вашого Договору оренди <b>№ {order.contract_number}</b>:\n\n"
                        f"<i>«{text}»</i>"
                    ),
                    reply_markup=client_kb,
                    parse_mode=ParseMode.HTML,
                )
                await msg.reply_text(
                    f"✅ Повідомлення від <b>{dept_label}</b> зафіксовано в журналі та надіслано клієнту.",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as err:
                await msg.reply_text(f"⚠️ Коментар збережено в журналі, але не вдалося доставити клієнту: {err}")
            return True

        if mode == "comment_internal":
            dept_label = pending.get("dept_label") or _resolve_department_label(pending.get("topic_key"), getattr(msg, "message_thread_id", None))
            await db.add_rental_audit_log(
                order_id=order.id,
                actor_id=user_id,
                actor_name=actor_name,
                actor_role=dept_label,
                action="STAFF_INTERNAL_NOTE",
                details=f"📌 Службова примітка: {text}",
            )
            await post_or_update_staff_order_card(context, order.id)
            if pending.get("topic_key") != "vuptap":
                try:
                    await send_to_staff_topic(
                        context,
                        "vuptap",
                        (
                            f"📌 <b>Службова примітка по Договору № {order.contract_number}</b>\n"
                            f"Підрозділ: <b>{dept_label}</b> ({actor_name})\n"
                            f"Текст: <i>«{text}»</i>"
                        ),
                    )
                except Exception:
                    pass
            await msg.reply_text(
                f"📌 Внутрішню службову примітку збережено у Зведеній картці та журналі дій.",
                parse_mode=ParseMode.HTML,
            )
            return True

        if mode == "slots":
            raw_slots = re.split(r"[,;\s]+", text)
            valid_slots = [s for s in raw_slots if re.match(r"^\d{1,2}:\d{2}$", s)]
            if not valid_slots:
                await msg.reply_text(
                    "⚠️ Не вдалося розпізнати формат часу. Надішліть години у форматі <code>12:00, 15:00</code>.",
                    parse_mode=ParseMode.HTML,
                )
                return True

            added = await db.add_rental_slots(
                rental_date=order.rental_date,
                slot_times=valid_slots,
                transport_type=order.transport_type,
                added_by_id=user_id,
                added_by_name=actor_name,
            )
            all_free = await db.get_available_rental_slots(order.rental_date, order.transport_type)
            await db.add_rental_audit_log(
                order_id=order.id,
                actor_id=user_id,
                actor_name=actor_name,
                actor_role="🚦 Служба руху",
                action="SLOTS_ADDED",
                details=f"Додано вільні слоти на {order.rental_date}: {', '.join(all_free)}",
            )

            # Оновлюємо всі замовлення, що очікували слотів на цю дату
            waiting_orders = await db.get_pending_slots_orders_for_date(order.rental_date, order.transport_type)
            if order.status == "pending_slots" and all(w.id != order.id for w in waiting_orders):
                waiting_orders.append(order)

            for w_order in waiting_orders:
                await db.update_rental_order_fields(w_order.id, {"status": "awaiting_slot_choice"})
                await post_or_update_staff_order_card(context, w_order.id)
                slot_buttons = [
                    [
                        InlineKeyboardButton(
                            f"🕒 Обрати {sl}",
                            callback_data=f"rental_pick_order_slot:{w_order.id}:{sl}",
                        )
                    ]
                    for sl in all_free
                ]
                slot_buttons.append(
                    [InlineKeyboardButton("📂 Мої діючі договори", callback_data="rental_my_contracts")]
                )
                try:
                    await context.bot.send_message(
                        chat_id=w_order.user_id,
                        text=(
                            f"🚦 <b>Служба руху КП «ОМЕТ» відкрила вільні часові слоти на {w_order.rental_date}!</b>\n\n"
                            f"За Вашим замовленням <b>№ {w_order.contract_number}</b> ({w_order.wagon_type}) "
                            f"оберіть зручний час подачі вагона зі списку нижче:"
                        ),
                        reply_markup=InlineKeyboardMarkup(slot_buttons),
                        parse_mode=ParseMode.HTML,
                    )
                except Exception as notify_err:
                    logger.warning(f"Не вдалося сповістити клієнта {w_order.user_id} про слоти: {notify_err}")

            await post_or_update_staff_order_card(context, order.id)
            await msg.reply_text(
                f"✅ Слоти на <b>{order.rental_date}</b> збережено в пулі: <b>{', '.join(all_free)}</b>.\n"
                f"Клієнту надіслано кнопки вибору часу.",
                parse_mode=ParseMode.HTML,
            )
            return True

        if mode == "depot":
            chunks = [c.strip() for c in text.split(",") if c.strip()]
            board_num = chunks[0] if len(chunks) >= 1 else text
            driver_name = chunks[1] if len(chunks) >= 2 else "Черговий водій-інструктор"
            driver_phone = chunks[2] if len(chunks) >= 3 else "Через диспетчера депо"

            updated_order = await db.update_rental_order_fields(
                order.id,
                {
                    "assigned_board_number": board_num,
                    "assigned_driver_name": driver_name,
                    "assigned_driver_phone": driver_phone,
                    "depot_assigned_by": actor_name,
                    "depot_assigned_at": datetime.datetime.now(),
                    "status": "vehicle_assigned",
                },
            )
            await db.add_rental_audit_log(
                order_id=order.id,
                actor_id=user_id,
                actor_name=actor_name,
                actor_role=f"🚋 Депо {order.depot_code}",
                action="VEHICLE_ASSIGNED",
                details=f"Призначено борт №{board_num}, водій: {driver_name} ({driver_phone})",
            )
            await post_or_update_staff_order_card(context, order.id)

            # Генеруємо та надсилаємо клієнту електронний посадковий талон із QR-кодом та пам'яткою ПБ
            if updated_order:
                safety_dt = getattr(updated_order, "safety_accepted_at", None)
                safety_str = safety_dt.strftime("%d.%m.%Y о %H:%M") if safety_dt else "Підтверджено електронно"
                pass_pdf = generate_rental_boarding_pass_pdf(
                    {
                        "contract_number": updated_order.contract_number,
                        "order_uid": updated_order.order_uid,
                        "rental_date": updated_order.rental_date,
                        "rental_time_slot": updated_order.rental_time_slot or "за графіком",
                        "pickup_stop": updated_order.pickup_stop,
                        "dropoff_stop": updated_order.dropoff_stop,
                        "wagon_type": updated_order.wagon_type,
                        "assigned_board_number": updated_order.assigned_board_number,
                        "assigned_driver_name": updated_order.assigned_driver_name,
                        "assigned_driver_phone": updated_order.assigned_driver_phone,
                        "user_full_name": updated_order.user_full_name,
                        "user_phone": updated_order.user_phone,
                        "safety_accepted_at": safety_str,
                    }
                )
                try:
                    with open(pass_pdf, "rb") as pf:
                        await context.bot.send_document(
                            chat_id=updated_order.user_id,
                            document=pf,
                            filename=os.path.basename(pass_pdf),
                            caption=(
                                f"🎫 <b>ЕЛЕКТРОННИЙ ПОСАДКОВИЙ ТАЛОН ЗА ДОГОВОРОМ № {updated_order.contract_number}</b>\n\n"
                                f"🚋 <b>Рухомий склад:</b> {updated_order.wagon_type}\n"
                                f"🔢 <b>Бортовий номер:</b> <b>№ {board_num}</b>\n"
                                f"👨‍✈️ <b>Водій:</b> {driver_name} (тел.: <code>{driver_phone}</code>)\n"
                                f"📅 <b>Подача на зупинку «{updated_order.pickup_stop}»:</b> {updated_order.rental_date} о {updated_order.rental_time_slot}\n\n"
                                f"🔥 <i>У документі також наведено обов'язкову пам'ятку з пожежної та електробезпеки для учасників поїздки.</i>\n"
                                f"Покажіть цей талон або QR-код водієві під час посадки. Гарної поїздки!"
                            ),
                            parse_mode=ParseMode.HTML,
                        )
                except Exception as send_err:
                    logger.warning(f"Не вдалося надіслати посадковий талон клієнту: {send_err}")

            await msg.reply_text(
                f"✅ Борт <b>№{board_num}</b> та водія <b>{driver_name}</b> призначено! "
                f"Клієнту автоматично надіслано електронний посадковий талон із QR-кодом та пам'яткою ПБ.",
                parse_mode=ParseMode.HTML,
            )
            return True

    # 2. Перевіряємо Reply на картку замовлення з префіксом 'Коментар:' або 'Інфо:'
    if msg.reply_to_message and msg.reply_to_message.text:
        m_Prefix = re.match(r"^(?:коментар|інфо|comment|info)\s*:\s*(.+)$", text, flags=re.IGNORECASE | re.DOTALL)
        if m_Prefix:
            comment_body = m_Prefix.group(1).strip()
            reply_text = msg.reply_to_message.text
            m_contract = re.search(r"№\s*([0-9]{4}-[0-9]{4}-О)", reply_text)
            if m_contract and comment_body:
                contract_number = m_contract.group(1)
                order = await db.get_rental_order_by_contract(contract_number)
                if order:
                    dept_label = _resolve_department_label(None, getattr(msg, "message_thread_id", None))
                    await db.add_rental_audit_log(
                        order_id=order.id,
                        actor_id=user_id,
                        actor_name=actor_name,
                        actor_role=dept_label,
                        action="STAFF_COMMENT",
                        details=f"Коментар клієнту: {comment_body}",
                    )
                    await post_or_update_staff_order_card(context, order.id)
                    try:
                        await context.bot.send_message(
                            chat_id=order.user_id,
                            text=(
                                f"💬 <b>Офіційне повідомлення від підрозділу «{dept_label}» КП «ОМЕТ»</b>\n"
                                f"Щодо Вашого Договору оренди <b>№ {order.contract_number}</b>:\n\n"
                                f"<i>«{comment_body}»</i>"
                            ),
                            parse_mode=ParseMode.HTML,
                        )
                        await msg.reply_text("✅ Ваш коментар зафіксовано в журналі та надіслано клієнту в Telegram.")
                    except Exception as err:
                        await msg.reply_text(f"⚠️ Коментар збережено в журналі, але не вдалося доставити клієнту: {err}")
                    return True

    return False


# ================= СЛУЖБОВІ КОМАНДИ ДЛЯ ВАЛЕНТИНА (/chatid, /set_rental_chat, /add_rental_role) =================

async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Повертає ID поточного чату та ID користувача (доступно Валентину)."""
    if not update.effective_user or not update.effective_chat:
        return
    if update.effective_user.id != VALENTIN_ADMIN_ID:
        return

    chat = update.effective_chat
    active_staff_chat = get_active_staff_chat_id()
    await update.message.reply_text(
        f"🆔 <b>Діагностика чату (Оренда КП ОМЕТ):</b>\n"
        f"• ID цього чату: <code>{chat.id}</code> ({chat.type})\n"
        f"• Ваш Telegram ID: <code>{update.effective_user.id}</code>\n"
        f"• Поточний штабний чат оренди: <code>{active_staff_chat}</code>\n\n"
        f"💡 Щоб зробити цей чат оперативним штабом оренди, надішліть тут команду:\n"
        f"<code>/set_rental_chat</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_set_rental_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Прив'язує поточну групу як оперативний штаб оренди КП ОМЕТ (доступно Валентину)."""
    if not update.effective_user or not update.effective_chat:
        return
    if update.effective_user.id != VALENTIN_ADMIN_ID:
        return

    chat_id = update.effective_chat.id
    cfg = _load_runtime_staff_config()
    cfg["staff_chat_id"] = chat_id
    _save_runtime_staff_config(cfg)

    await update.message.reply_text(
        f"✅ <b>Чат успішно прив'язано як Оперативний Штаб Оренди КП «ОМЕТ»!</b>\n"
        f"ID штабного чату: <code>{chat_id}</code>\n\n"
        f"Усі нові картки замовлень, підписані договори (.p7s / скани) та квитанції IBAN надходитимуть сюди.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_add_rental_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Додає Telegram ID співробітника до відповідної ролі: /add_rental_role <role> <telegram_id>."""
    if not update.effective_user or update.effective_user.id != VALENTIN_ADMIN_ID:
        return
    args = context.args or []
    if len(args) < 2 or args[0] not in ROLE_TITLES_UA:
        roles_help = "\n".join(f"• <code>{k}</code> — {v}" for k, v in ROLE_TITLES_UA.items())
        await update.message.reply_text(
            f"ℹ️ <b>Використання:</b> <code>/add_rental_role &lt;роль&gt; &lt;telegram_id&gt;</code>\n\n"
            f"Доступні ролі:\n{roles_help}",
            parse_mode=ParseMode.HTML,
        )
        return

    role_key = args[0]
    try:
        target_uid = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Telegram ID має бути числом.")
        return

    cfg = _load_runtime_staff_config()
    roles_map = cfg.setdefault("roles", {})
    uid_list = [int(x) for x in roles_map.get(role_key, [])]
    if target_uid not in uid_list:
        uid_list.append(target_uid)
    roles_map[role_key] = uid_list
    _save_runtime_staff_config(cfg)

    await update.message.reply_text(
        f"✅ Користувачу <code>{target_uid}</code> надано роль <b>{ROLE_TITLES_UA[role_key]}</b>.",
        parse_mode=ParseMode.HTML,
    )


# ================= ФОНОВИЙ КОНТРОЛЬ 36-ГОДИННОГО ТАЙМ-АУТУ ПІДПИСАННЯ =================

async def check_rental_timeouts_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Перевіряє прострочені договори оренди ('awaiting_signature'), автоматично
    звільняє їхні часові слоти після спливу 36 годин та оновлює картки у штабному чаті.
    """
    try:
        expired_orders = await db.expire_overdue_rental_orders()
        for order in expired_orders:
            await post_or_update_staff_order_card(context, order.id)
            try:
                await send_to_staff_topic(
                    context,
                    "vuptap",
                    (
                        f"⌛ <b>Замовлення скасовано (тайм-аут 36 годин)!</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"Договір: <b>№ {order.contract_number}</b>\n"
                        f"Замовник: {order.user_full_name} ({order.user_phone})\n"
                        f"Підписаний договір не завантажено у 36-годинний термін.\n"
                        f"Часовий слот ({order.rental_date} {order.rental_time_slot or ''}) автоматично повернено в пул."
                    ),
                )
            except Exception:
                pass
            try:
                await context.bot.send_message(
                    chat_id=order.user_id,
                    text=(
                        f"⌛ <b>Час бронювання слоту за Договором № {order.contract_number} вичерпано (36 годин).</b>\n\n"
                        f"Оскільки підписаний договір не було завантажено у встановлений термін, бронювання часу "
                        f"({order.rental_date} {order.rental_time_slot or ''}) автоматично знято. "
                        f"Ви можете оформити нову заявку в розділі «🚋 Оренда та екскурсії»."
                    ),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
    except Exception as exc:
        logger.error(f"Помилка перевірки 36-годинних тайм-аутів оренди: {exc}")


def is_rental_staff_member(user_id: int, chat_id: Optional[int] = None) -> bool:
    """Перевіряє, чи має користувач повноваження співробітника штабу оренди."""
    if int(user_id) == VALENTIN_ADMIN_ID or int(user_id) in RENTAL_ALLOWED_USER_IDS:
        return True
    if chat_id is not None and int(chat_id) == get_active_staff_chat_id():
        return True
    cfg = _load_runtime_staff_config()
    for role_uids in cfg.get("roles", {}).values():
        if int(user_id) in [int(x) for x in role_uids]:
            return True
    return False


async def cmd_bind_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Прив'язує тему (Forum Topic) до відповідного підрозділу штабу оренди.
    Доступно адміністратору (Валентину).
    Використання:
    1) Всередині самої теми супергрупи:
       /bind_topic vuptap
    2) Або з явним thread_id:
       /bind_topic vuptap 1234
    """
    if not update.effective_user or not update.effective_message:
        return
    if update.effective_user.id != VALENTIN_ADMIN_ID:
        return

    args = context.args or []
    if not args or args[0] not in TOPIC_KEYS:
        keys_help = "\n".join(f"• <code>{k}</code> — {TOPIC_TITLES_UA[k]}" for k in TOPIC_KEYS)
        await update.message.reply_text(
            f"ℹ️ <b>Використання:</b> <code>/bind_topic &lt;ключ_теми&gt; [thread_id]</code>\n\n"
            f"<i>Якщо надіслати команду всередині відповідної теми в групі, ID теми підхопиться автоматично!</i>\n\n"
            f"Доступні ключі тем:\n{keys_help}",
            parse_mode=ParseMode.HTML,
        )
        return

    topic_key = args[0]
    thread_id = None
    if len(args) >= 2:
        try:
            thread_id = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ thread_id має бути числом.")
            return
    elif update.message.message_thread_id:
        thread_id = update.message.message_thread_id
    elif getattr(update.message, "is_topic_message", False) and update.message.message_thread_id:
        thread_id = update.message.message_thread_id

    if thread_id is None:
        await update.message.reply_text(
            "⚠️ Не вдалося визначити ID теми. Надішліть цю команду безпосередньо всередині цільової теми "
            "або вкажіть ID теми вручну: <code>/bind_topic vuptap 123</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    cfg = _load_runtime_staff_config()
    cfg.setdefault("topics", {})
    cfg["topics"][topic_key] = thread_id
    if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
        cfg["staff_chat_id"] = update.effective_chat.id
    _save_runtime_staff_config(cfg)

    await update.message.reply_text(
        f"✅ Тему <b>{TOPIC_TITLES_UA[topic_key]}</b> успішно прив'язано до потоку (thread ID: <code>{thread_id}</code>)!\n"
        f"Усі повідомлення, документи та завдання підрозділу надходитимуть сюди.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_topics_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відображає поточний статус прив'язки тем супергрупи штабу оренди."""
    if not update.effective_user or update.effective_user.id != VALENTIN_ADMIN_ID:
        return

    cfg = _load_runtime_staff_config()
    active_chat = cfg.get("staff_chat_id", RENTAL_STAFF_CHAT_ID)
    topics = cfg.get("topics", {})

    lines = [
        "🏛️ <b>СТАТУС ТЕМ ШТАБУ ОРЕНДИ КП «ОМЕТ»</b>",
        f"Штабний чат ID: <code>{active_chat}</code>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    for k in TOPIC_KEYS:
        tid = topics.get(k)
        status_icon = "🟢" if tid is not None else "⚪ (не прив'язано)"
        thread_str = f"thread_id: <code>{tid}</code>" if tid is not None else "надсилається у загальний чат"
        lines.append(f"{status_icon} <b>{TOPIC_TITLES_UA[k]}</b> (<code>{k}</code>)\n   ↳ {thread_str}")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        "💡 <i>Щоб прив'язати тему, увійдіть у потрібну гілку та напишіть:</i>\n"
        "<code>/bind_topic vuptap</code> (або <code>depot</code>, <code>accounting</code>, <code>legal</code>, <code>analytics</code>)"
    )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ================= ПУЛЬТ КЕРУВАННЯ СЛОТАМИ ДЛЯ ТЕМИ «ДЕПО ТА ВРМ» =================

def render_depot_slots_menu() -> Tuple[str, InlineKeyboardMarkup]:
    """Формує головне меню пульта керування вільними слотами для Депо."""
    text = (
        "🚋 <b>ПУЛЬТ КЕРУВАННЯ СЛОТАМИ (ДЕПО ТА ВРМ)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Тут чергові майстри та диспетчери Депо можуть додавати нові доступні години випуску "
        "ретро-трамваїв на конкретні дати, або видаляти помилково створені вільні слоти.\n\n"
        "Оберіть дію:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Додати вільні слоти на дату", callback_data="depot_slots:add_prompt")],
        [InlineKeyboardButton("🗑️ Видалити вільні слоти з дати", callback_data="depot_slots:del_date_list")],
        [InlineKeyboardButton("🔄 Оновити статус", callback_data="depot_slots:menu")],
    ])
    return text, kb


async def cmd_depot_slots_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відкриває пульт керування слотами для Депо та ВРМ."""
    if not update.effective_user or not update.effective_message:
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not is_rental_staff_member(user_id, chat_id):
        return

    text, kb = render_depot_slots_menu()
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def handle_depot_slots_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє натискання кнопок у пульті слотів Депо (додавання / перегляд / видалення)."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    user = update.effective_user
    user_id = user.id
    actor_name = user.full_name or user.username or str(user_id)
    chat_id = update.effective_chat.id if update.effective_chat else None

    if not is_rental_staff_member(user_id, chat_id):
        await query.answer("⛔ Доступ до пульта Депо обмежено для співробітників.", show_alert=True)
        return

    data = query.data
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "menu":
        text, kb = render_depot_slots_menu()
        await query.answer()
        try:
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    if action == "add_prompt":
        _PENDING_STAFF_INPUT[(chat_id, user_id)] = {"mode": "depot_add_slot"}
        await query.answer("Режим додавання активовано")
        await query.edit_message_text(
            "➕ <b>ДОДАВАННЯ ВІЛЬНИХ СЛОТІВ ДЛЯ РЕТРО-ТРАМВАЇВ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Надішліть у відповідь дату та перелік годин подачі вагона через кому або пробіл:\n\n"
            "Формат: <code>ДД.ММ.РРРР ГГ:ХХ, ГГ:ХХ</code>\n"
            "Приклад:\n<code>15.05.2026 11:00, 14:00, 17:00</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Скасувати", callback_data="depot_slots:menu")]
            ]),
            parse_mode=ParseMode.HTML,
        )
        return

    if action == "del_date_list":
        dates = await db.get_dates_with_free_slots()
        await query.answer()
        if not dates:
            await query.edit_message_text(
                "ℹ️ <b>Наразі в системі немає дат із вільними слотами для видалення.</b>\n"
                "Усі наявні слоти вже заброньовані клієнтами або ще не створювалися.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Назад до пульта Депо", callback_data="depot_slots:menu")]
                ]),
                parse_mode=ParseMode.HTML,
            )
            return

        keyboard_buttons = []
        row = []
        for d in dates:
            row.append(InlineKeyboardButton(f"📅 {d}", callback_data=f"depot_slots:pick_del_date:{d}"))
            if len(row) == 2:
                keyboard_buttons.append(row)
                row = []
        if row:
            keyboard_buttons.append(row)
        keyboard_buttons.append([InlineKeyboardButton("⬅️ Назад до пульта Депо", callback_data="depot_slots:menu")])

        await query.edit_message_text(
            "🗑️ <b>Оберіть дату, на якій потрібно видалити вільні слоти:</b>",
            reply_markup=InlineKeyboardMarkup(keyboard_buttons),
            parse_mode=ParseMode.HTML,
        )
        return

    if action == "pick_del_date":
        if len(parts) < 3:
            return
        target_date = parts[2]
        slots = await db.get_all_rental_slots_for_date(target_date)
        free_slots = [s for s in slots if s.status == "free"]
        await query.answer()

        if not free_slots:
            await query.edit_message_text(
                f"ℹ️ На дату <b>{target_date}</b> немає вільних слотів (усі вже зайняті або заблоковані).",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ До списку дат", callback_data="depot_slots:del_date_list")]
                ]),
                parse_mode=ParseMode.HTML,
            )
            return

        slot_buttons = []
        row = []
        for s in free_slots:
            row.append(InlineKeyboardButton(f"❌ {s.slot_time}", callback_data=f"depot_slots:confirm_del:{s.id}:{target_date}"))
            if len(row) == 3:
                slot_buttons.append(row)
                row = []
        if row:
            slot_buttons.append(row)

        slot_buttons.append([InlineKeyboardButton("⬅️ До списку дат", callback_data="depot_slots:del_date_list")])
        slot_buttons.append([InlineKeyboardButton("🚋 До пульта Депо", callback_data="depot_slots:menu")])

        await query.edit_message_text(
            f"🗑️ <b>Вільні слоти на дату {target_date}:</b>\n\n"
            f"<i>Натисніть на час, який необхідно вилучити з розкладу:</i>",
            reply_markup=InlineKeyboardMarkup(slot_buttons),
            parse_mode=ParseMode.HTML,
        )
        return

    if action == "confirm_del":
        if len(parts) < 4:
            return
        slot_id = int(parts[2])
        target_date = parts[3]

        success = await db.delete_rental_slot_by_id(slot_id)
        if not success:
            await query.answer("⚠️ Слот уже заброньовано або не існує!", show_alert=True)
            return

        await db.add_rental_audit_log(
            order_id=0,
            actor_id=user_id,
            actor_name=actor_name,
            actor_role="ДЕПО та ВРМ",
            action="SLOT_DELETED",
            details=f"Видалено вільний слот #{slot_id} на дату {target_date}",
        )
        await query.answer("✅ Слот успішно видалено!", show_alert=False)

        slots = await db.get_all_rental_slots_for_date(target_date)
        free_slots = [s for s in slots if s.status == "free"]
        if not free_slots:
            await query.edit_message_text(
                f"✅ Усі вільні слоти на дату <b>{target_date}</b> видалено.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ До списку дат", callback_data="depot_slots:del_date_list")],
                    [InlineKeyboardButton("🚋 До пульта Депо", callback_data="depot_slots:menu")],
                ]),
                parse_mode=ParseMode.HTML,
            )
            return

        slot_buttons = []
        row = []
        for s in free_slots:
            row.append(InlineKeyboardButton(f"❌ {s.slot_time}", callback_data=f"depot_slots:confirm_del:{s.id}:{target_date}"))
            if len(row) == 3:
                slot_buttons.append(row)
                row = []
        if row:
            slot_buttons.append(row)

        slot_buttons.append([InlineKeyboardButton("⬅️ До списку дат", callback_data="depot_slots:del_date_list")])
        slot_buttons.append([InlineKeyboardButton("🚋 До пульта Депо", callback_data="depot_slots:menu")])

        await query.edit_message_text(
            f"🗑️ <b>Вільні слоти на дату {target_date}:</b>\n\n"
            f"<i>Слот видалено! Натисніть на інший час, якщо потрібно видалити ще:</i>",
            reply_markup=InlineKeyboardMarkup(slot_buttons),
            parse_mode=ParseMode.HTML,
        )
        return


# ================= ІНТЕРАКТИВНИЙ АНАЛІТИЧНИЙ ПУЛЬТ ДЛЯ ТЕМИ «АНАЛІТИКА ДІЙ ПРАЦІВНИКІВ» =================

def render_analytics_main_menu() -> Tuple[str, InlineKeyboardMarkup]:
    """Формує головне інтерактивне меню пульта аналітики дій працівників."""
    text = (
        "📊 <b>АНАЛІТИЧНИЙ ПУЛЬТ ОРЕНДИ ТРАМВАЇВ КП «ОМЕТ»</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Оберіть потрібний звіт або аналітику дій підрозділів:\n\n"
        "• <b>Звіт за тиждень</b> — зведені KPI, дохід, пробіг Wialon, SLA підрозділів\n"
        "• <b>Звіт за місяць</b> — повна динаміка виконання та завантаження\n"
        "• <b>Звіт по замовленню</b> — детальний хронометраж узгодження конкретного договору\n"
        "• <b>Останні дії персоналу</b> — журнал аудиту (Audit Log) в реальному часі"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Звіт за 7 днів (тиждень)", callback_data="rental_analytics:week")],
        [InlineKeyboardButton("📅 Звіт за 30 днів (місяць)", callback_data="rental_analytics:month")],
        [InlineKeyboardButton("📑 Звіт по замовленню", callback_data="rental_analytics:orders")],
        [InlineKeyboardButton("📋 Останні дії персоналу", callback_data="rental_analytics:actions")],
        [InlineKeyboardButton("🔄 Оновити пульт", callback_data="rental_analytics:menu")],
    ])
    return text, kb


async def render_period_analytics_text(days: int) -> str:
    """Генерує текстовий звіт за вказаний період (тиждень / місяць)."""
    data = await db.get_rental_period_analytics(days=days)
    period_title = "7 ДНІВ (ТИЖДЕНЬ)" if days == 7 else f"{days} ДНІВ (МІСЯЦЬ)"
    sla = data.get("avg_sla_min", {})

    def fmt_sla(val: Optional[float]) -> str:
        if val is None:
            return "немає даних"
        if val < 60:
            return f"~{int(val)} хв"
        hours = int(val // 60)
        mins = int(val % 60)
        return f"~{hours} год {mins} хв"

    return (
        f"📊 <b>ЗВІДНИЙ ЗВІТ МОДУЛЯ ОРЕНДИ ЗА {period_title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>Загальна кількість замовлень:</b> <b>{data['total_orders']}</b>\n"
        f"• ✅ Успішно виконано: <b>{data['completed_orders']}</b>\n"
        f"• ⏳ В роботі / на погодженні: <b>{data['active_orders']}</b>\n"
        f"• 🚫 Скасовано / прострочено: <b>{data['cancelled_orders']}</b>\n\n"
        f"💰 <b>Фінансові показники (офіційний IBAN):</b>\n"
        f"• Загальний дохід: <b>{data['total_revenue_uah']:,.2f} грн</b>\n"
        f"• Без ПДВ: {data['without_vat_uah']:,.2f} грн\n"
        f"• ПДВ (20%): {data['vat_uah']:,.2f} грн\n\n"
        f"🚋 <b>Рухомий склад та Wialon:</b>\n"
        f"• Загальний кілометраж Wialon: <b>{data['total_km']:.2f} км</b>\n"
        f"• Ретро МТВ-82: <b>{data['mtv_count']}</b> замовлень\n"
        f"• Відкритий №914: <b>{data['open_914_count']}</b> замовлень\n\n"
        f"⏱️ <b>Середній час реакції служб (SLA):</b>\n"
        f"• 🚦 Служба руху (ВУПтаП): <b>{fmt_sla(sla.get('vuptap'))}</b>\n"
        f"• ⚖️ Юридичний відділ: <b>{fmt_sla(sla.get('legal'))}</b>\n"
        f"• 💳 Бухгалтерія: <b>{fmt_sla(sla.get('accounting'))}</b>\n"
        f"• 🚋 ДЕПО та ВРМ: <b>{fmt_sla(sla.get('depot'))}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Дані розраховано на основі журналу дій та системи Wialon.</i>"
    )


async def render_recent_orders_menu() -> Tuple[str, InlineKeyboardMarkup]:
    """Генерує меню вибору замовлення для детального аудиту."""
    orders = await db.get_recent_rental_orders(limit=10)
    if not orders:
        text = (
            "📑 <b>АНАЛІТИКА ЗАМОВЛЕНЬ</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            "ℹ️ В базі даних ще немає зареєстрованих замовлень оренди."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ До головної аналітики", callback_data="rental_analytics:menu")]
        ])
        return text, kb

    text = (
        "📑 <b>АНАЛІТИКА ОКРЕМИХ ЗАМОВЛЕНЬ</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "Оберіть договір зі списку останніх для перегляду детального хронометражу та аудиту дій підрозділів:"
    )
    buttons = []
    status_emoji_map = {
        "completed": "✅",
        "vehicle_assigned": "🚋",
        "paid_confirmed": "💳",
        "legal_approved": "⚖️",
        "revision_requested": "⚠️",
        "awaiting_payment": "⏳",
        "awaiting_signature": "✍️",
        "pending_slots": "🕒",
        "cancelled": "🚫",
        "expired_36h": "⌛",
    }
    for ord_item in orders:
        em = status_emoji_map.get(ord_item.status, "📋")
        btn_text = f"{em} №{ord_item.contract_number} | {ord_item.rental_date} | {float(ord_item.total_price_uah or 0):.0f} грн"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"rental_analytics:order:{ord_item.id}")])

    buttons.append([InlineKeyboardButton("⬅️ До головної аналітики", callback_data="rental_analytics:menu")])
    return text, InlineKeyboardMarkup(buttons)


async def render_order_timeline_text(order_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """Генерує деталізований таймлайн погодження замовлення підрозділами штабу."""
    data = await db.get_order_timeline_analytics(order_id)
    if not data or not data.get("order"):
        text = "❌ Замовлення не знайдено."
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ До списку замовлень", callback_data="rental_analytics:orders")]
        ])
        return text, kb

    order = data["order"]
    logs = data.get("logs", [])

    lines = [
        f"📑 <b>ХРОНОМЕТРАЖ ТА АУДИТ ДОГОВОРУ № {order.contract_number}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"👤 <b>Замовник:</b> {order.user_full_name} ({order.user_phone})",
        f"🚋 <b>Вагон:</b> {order.wagon_type}",
        f"📅 <b>Дата та час рейсу:</b> {order.rental_date} о {order.rental_time_slot or 'не узгоджено'}",
        f"📍 <b>Маршрут:</b> {order.pickup_stop} ➡️ {order.dropoff_stop}",
        f"💰 <b>Сума до сплати:</b> {float(order.total_price_uah or 0):.2f} грн",
        f"🚥 <b>Поточний статус:</b> <code>{order.status}</code>",
        "━━━━━━━━━━━━━━━━━━━━",
        "📜 <b>ТАЙМЛАЙН ДІЙ ПІДРОЗДІЛІВ:</b>",
    ]

    if not logs:
        lines.append("<i>Журнал дій порожній</i>")
    else:
        for idx, lg in enumerate(logs, start=1):
            t_str = lg.created_at.strftime("%d.%m.%Y %H:%M") if lg.created_at else "—"
            lines.append(
                f"{idx}. <b>{t_str}</b> | <b>{lg.actor_role or 'Система'}</b> ({lg.actor_name or '—'})\n"
                f"   ↳ <i>{lg.details or lg.action}</i>"
            )

    lines.append("━━━━━━━━━━━━━━━━━━━━")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ До списку замовлень", callback_data="rental_analytics:orders")],
        [InlineKeyboardButton("📊 Головна панель аналітики", callback_data="rental_analytics:menu")],
    ])
    return "\n".join(lines), kb


async def render_recent_actions_text() -> Tuple[str, InlineKeyboardMarkup]:
    """Генерує перегляд останніх дій співробітників у журналі аудиту."""
    logs = await db.get_recent_audit_actions(limit=10)
    lines = [
        "📋 <b>ЖУРНАЛ ОСТАННІХ ДІЙ ПЕРСОНАЛУ (AUDIT LOG)</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if not logs:
        lines.append("<i>Записів у журналі аудиту поки що немає.</i>")
    else:
        for idx, lg in enumerate(logs, start=1):
            t_str = lg.created_at.strftime("%d.%m %H:%M") if lg.created_at else "—"
            order_ref = f"№{lg.order_id}" if lg.order_id else "Загальне"
            lines.append(
                f"{idx}. <b>{t_str}</b> [{order_ref}] <b>{lg.actor_role}</b> ({lg.actor_name}):\n"
                f"   ↳ <code>{lg.action}</code>: {lg.details}"
            )
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Оновити", callback_data="rental_analytics:actions")],
        [InlineKeyboardButton("⬅️ Назад до аналітики", callback_data="rental_analytics:menu")],
    ])
    return "\n".join(lines), kb


async def cmd_analytics_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відкриває інтерактивний аналітичний пульт у темі 'Аналітика дій працівників'."""
    if not update.effective_user or not update.effective_message:
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not is_rental_staff_member(user_id, chat_id):
        return

    text, kb = render_analytics_main_menu()
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def handle_analytics_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє виклики аналітичного пульта КП «ОМЕТ» (тижневі, місячні, по замовленнях)."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id if update.effective_chat else None

    if not is_rental_staff_member(user_id, chat_id):
        await query.answer("⛔ Доступ до аналітики обмежено для співробітників.", show_alert=True)
        return

    data = query.data
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "menu":
        text, kb = render_analytics_main_menu()
        await query.answer()
        try:
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    if action in ("week", "month"):
        days = 7 if action == "week" else 30
        text = await render_period_analytics_text(days)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Оновити показники", callback_data=f"rental_analytics:{action}")],
            [InlineKeyboardButton("⬅️ Назад до панелі аналітики", callback_data="rental_analytics:menu")],
        ])
        await query.answer()
        try:
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    if action == "orders":
        text, kb = await render_recent_orders_menu()
        await query.answer()
        try:
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    if action == "order":
        if len(parts) < 3:
            return
        order_id = int(parts[2])
        text, kb = await render_order_timeline_text(order_id)
        await query.answer()
        try:
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    if action == "actions":
        text, kb = await render_recent_actions_text()
        await query.answer()
        try:
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return
