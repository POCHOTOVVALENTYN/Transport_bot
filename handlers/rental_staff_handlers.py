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
    "traffic_service": "🚦 Служба руху",
    "legal_dept": "⚖️ Юридичний відділ",
    "vuptap_dept": "🛡️ ВУПтаП (Безпека руху)",
    "accounting_dept": "💳 Бухгалтерія",
    "depot_tram": "🚋 Трамвайне депо / ВРМ",
    "depot_trolley": "🚎 Тролейбусне депо",
}

# Двоетапне підтвердження натискання: (user_id, order_id, action_key) -> timestamp
_PENDING_CONFIRMATIONS: Dict[Tuple[int, int, str], float] = {}

# Очікування текстового вводу від співробітника: (chat_id, user_id) -> {"mode": "slots"|"depot", "order_id": int}
_PENDING_STAFF_INPUT: Dict[Tuple[int, int], Dict[str, Any]] = {}


def is_rental_access_allowed(user_id: int) -> bool:
    """
    Перевіряє, чи має користувач доступ до нового розділу оренди.
    Поки RENTAL_PUBLIC_ENABLED = False, розділ бачить ВИКЛЮЧНО Валентин (830196453).
    """
    if RENTAL_PUBLIC_ENABLED:
        return True
    return int(user_id) in RENTAL_ALLOWED_USER_IDS or int(user_id) == VALENTIN_ADMIN_ID


def _load_runtime_staff_config() -> Dict[str, Any]:
    if STAFF_CONFIG_FILE.exists():
        try:
            with open(STAFF_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning(f"Не вдалося прочитати {STAFF_CONFIG_FILE}: {exc}")
    return {"staff_chat_id": RENTAL_STAFF_CHAT_ID, "roles": {}}


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


def has_staff_role(user_id: int, role_key: str) -> bool:
    """Перевіряє наявність ролі у співробітника. Валентин має повний доступ до всіх 6 ролей."""
    uid = int(user_id)
    if uid == VALENTIN_ADMIN_ID:
        return True
    base_ids = RENTAL_STAFF_ROLES.get(role_key, [])
    if uid in base_ids:
        return True
    cfg = _load_runtime_staff_config()
    extra_ids = cfg.get("roles", {}).get(role_key, [])
    return uid in [int(x) for x in extra_ids]


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
    "legal_approved": "⚖️ Договір погоджено Юрвідділом — очікує підтвердження IBAN",
    "paid_confirmed": "💳 Оплату IBAN підтверджено — очікує призначення вагона та водія в депо",
    "vehicle_assigned": "✅ Вагон та водія призначено (посадковий талон видано)",
    "completed": "🏁 Рейс успішно виконано",
    "expired_36h": "⌛ Скасовано автоматично (перевищено ліміт 36 год)",
    "cancelled": "🚫 Скасовано",
}


async def format_staff_order_card_text(order: RentalOrder) -> str:
    """Формує повний текст інтерактивної картки замовлення для спільного штабного чату."""
    logs = await db.get_rental_audit_logs(order.id, limit=12)
    via_loops: List[str] = []
    try:
        via_loops = json.loads(order.via_loops_json or "[]")
    except Exception:
        via_loops = []

    via_str = " ➡️ ".join(via_loops) if via_loops else "прямий рейс"
    route_chain = f"{order.pickup_stop} ➡️ [{via_str}] ➡️ {order.dropoff_stop}"

    extras: List[str] = []
    try:
        extras = json.loads(order.extra_services_json or "[]")
    except Exception:
        extras = []
    extras_str = ", ".join(extras) if extras else "немає"

    scenario_str = (
        "📱 Електронний (Дія.Підпис / КЕП .p7s)"
        if order.signing_scenario == "kep"
        else "🏢 Паперовий в Управлінні КП (вул. Водопровідна, 1 — ліміт 36 год)"
    )

    deadline_str = "—"
    if order.slot_lock_expires_at:
        deadline_str = order.slot_lock_expires_at.strftime("%d.%m.%Y %H:%M")

    # Відмітки 6 підрозділів
    traffic_mark = f"✅ {order.traffic_approved_by}" if order.traffic_approved_by else "⏳ очікує"
    legal_mark = f"✅ {order.legal_approved_by}" if order.legal_approved_by else "⏳ очікує"
    vuptap_mark = f"✅ {order.vuptap_approved_by}" if order.vuptap_approved_by else "⏳ очікує"
    acc_mark = f"✅ {order.accounting_approved_by}" if order.accounting_approved_by else "⏳ очікує"
    if order.assigned_board_number:
        depot_mark = (
            f"✅ Борт №{order.assigned_board_number}, водій {order.assigned_driver_name or '—'} "
            f"({order.assigned_driver_phone or '—'}) [{order.depot_assigned_by or 'Депо'}]"
        )
    else:
        depot_mark = "⏳ очікує призначення борту та водія"

    audit_lines: List[str] = []
    for entry in logs:
        ts_str = entry.created_at.strftime("%d.%m %H:%M") if entry.created_at else "--:--"
        audit_lines.append(
            f"• <code>{ts_str}</code> | <b>{entry.actor_role}</b> ({entry.actor_name}): {entry.details or entry.action}"
        )
    audit_block = "\n".join(audit_lines) if audit_lines else "• Журнал порожній"

    billable_min = max(60, int(order.total_duration_min or 0))
    min_tag = " (застосовано мін. 1 год)" if billable_min > (order.total_duration_min or 0) else ""
    vat_val = round(order.total_price_uah / 6.0, 2)
    cust_type_label = {
        "individual": "🚶 Фізособа",
        "fop": "💼 ФОП",
        "legal_entity": "🏢 Юрособа",
    }.get(getattr(order, "customer_type", "individual") or "individual", "🚶 Фізособа")

    return (
        f"🚋 <b>КАРТКА ЗАМОВЛЕННЯ ОРЕНДИ № {order.contract_number}</b>\n"
        f"🆔 Код: <code>{order.order_uid}</code> | Статус: <b>{STATUS_LABELS_UA.get(order.status, order.status)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Замовник ({cust_type_label}):</b> {order.user_full_name}\n"
        f"📞 <b>Телефон:</b> <code>{order.user_phone}</code> | <b>РНОКПП/ЄДРПОУ:</b> <code>{order.user_tax_id or '—'}</code>\n"
        f"📅 <b>Дата та слот:</b> <b>{order.rental_date}</b> | Час: <b>{order.rental_time_slot or 'ПОТРІБНІ СЛОТИ СЛУЖБИ РУХУ'}</b>\n"
        f"⏳ <b>Бронь слоту діє до:</b> {deadline_str}\n"
        f"📝 <b>Сценарій договору:</b> {scenario_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🚊 <b>Рухомий склад:</b> {order.wagon_type} (Депо: <b>{order.depot_code}</b>)\n"
        f"🗺️ <b>Маршрут (посадка/висадка тільки на кільцях):</b>\n"
        f"   {route_chain}\n"
        f"📏 <b>Телеметрія Wialon:</b> <b>{order.total_distance_km:.2f} км</b> | факт: <b>{order.total_duration_min} хв</b> "
        f"(оплачуваний час: <b>{billable_min} хв</b>{min_tag})\n"
        f"   • Подача з {order.depot_code}: {order.distance_pull_out_km:.2f} км ({order.duration_pull_out_min} хв)\n"
        f"   • Маршрут клієнта: {order.distance_route_km:.2f} км ({order.duration_route_min} хв + стоянка {order.wait_minutes} хв)\n"
        f"   • Заїзд у {order.depot_code}: {order.distance_pull_in_km:.2f} км ({order.duration_pull_in_min} хв)\n"
        f"🎁 <b>Додаткові послуги:</b> {extras_str}\n"
        f"💰 <b>Сума за договором (IBAN з ПДВ 20%):</b> <b>{order.total_price_uah:.2f} грн</b> "
        f"(у т.ч. ПДВ 20%: {vat_val:.2f} грн)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ <b>ПОГОДЖЕННЯ ПІДРОЗДІЛІВ КП ОМЕТ:</b>\n"
        f"1️⃣ 🚦 Служба руху: {traffic_mark}\n"
        f"2️⃣ ⚖️ Юридичний відділ: {legal_mark}\n"
        f"3️⃣ 🛡️ ВУПтаП (Безпека руху): {vuptap_mark}\n"
        f"4️⃣ 💳 Бухгалтерія (IBAN): {acc_mark}\n"
        f"5️⃣ 🚋 Депо ({order.depot_code}): {depot_mark}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>ДЕТАЛІЗОВАНИЙ ЖУРНАЛ ЗАМОВЛЕННЯ:</b>\n"
        f"{audit_block}\n\n"
        f"💬 <i>Підказка: щоб надіслати повідомлення клієнту, зробіть Reply на цю картку з текстом:</i>\n"
        f"<code>Коментар: текст для клієнта</code>"
    )


def build_staff_order_keyboard(order: RentalOrder) -> InlineKeyboardMarkup:
    """Формує інлайн-клавіатуру картки замовлення для 6 підрозділів."""
    oid = order.id
    rows: List[List[InlineKeyboardButton]] = []

    if order.status not in ("cancelled", "expired_36h", "completed"):
        # Рядок 1: Служба руху
        rows.append(
            [
                InlineKeyboardButton(
                    "🚦 Служба руху: Погодити слот",
                    callback_data=f"rental_staff:traffic_ok:{oid}",
                ),
                InlineKeyboardButton(
                    "➕ Додати слоти на дату",
                    callback_data=f"rental_staff:add_slots:{oid}",
                ),
            ]
        )
        # Рядок 2: Юрвідділ + ВУПтаП
        rows.append(
            [
                InlineKeyboardButton(
                    "⚖️ Юрвідділ: Договір ОК",
                    callback_data=f"rental_staff:legal_ok:{oid}",
                ),
                InlineKeyboardButton(
                    "🛡️ ВУПтаП: Інструктаж ОК",
                    callback_data=f"rental_staff:vuptap_ok:{oid}",
                ),
            ]
        )
        # Рядок 3: Бухгалтерія + Депо
        rows.append(
            [
                InlineKeyboardButton(
                    "💳 Бухгалтерія: IBAN оплачено",
                    callback_data=f"rental_staff:acc_ok:{oid}",
                ),
                InlineKeyboardButton(
                    f"🚋 Депо ({order.depot_code}): Призначити борт",
                    callback_data=f"rental_staff:depot_assign:{oid}",
                ),
            ]
        )
        # Рядок 4: Завершення / Скасування
        rows.append(
            [
                InlineKeyboardButton(
                    "🏁 Рейс виконано",
                    callback_data=f"rental_staff:complete:{oid}",
                ),
                InlineKeyboardButton(
                    "🚫 Скасувати замовлення",
                    callback_data=f"rental_staff:cancel:{oid}",
                ),
            ]
        )

    return InlineKeyboardMarkup(rows)


async def post_or_update_staff_order_card(
    context: ContextTypes.DEFAULT_TYPE,
    order_id: int,
) -> Optional[int]:
    """
    Публікує нову або оновлює існуючу живу картку замовлення в оперативному чаті КП ОМЕТ.
    Якщо штабна група ще не прив'язана, надсилає картку Валентину (830196453).
    """
    order = await db.get_rental_order(order_id)
    if not order:
        return None

    card_text = await format_staff_order_card_text(order)
    markup = build_staff_order_keyboard(order)
    target_chat_id = order.staff_chat_id or get_active_staff_chat_id()

    if order.staff_chat_message_id and order.staff_chat_id:
        try:
            await context.bot.edit_message_text(
                chat_id=order.staff_chat_id,
                message_id=order.staff_chat_message_id,
                text=card_text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
            )
            return order.staff_chat_message_id
        except Exception as edit_err:
            if "Message is not modified" in str(edit_err):
                return order.staff_chat_message_id
            logger.warning(f"Не вдалося оновити картку замовлення #{order.id}, створюємо нову: {edit_err}")

    try:
        sent_msg = await context.bot.send_message(
            chat_id=target_chat_id,
            text=card_text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )
        await db.update_rental_order_fields(
            order.id,
            {
                "staff_chat_id": target_chat_id,
                "staff_chat_message_id": sent_msg.message_id,
            },
        )
        return sent_msg.message_id
    except Exception as send_err:
        logger.error(f"Помилка відправки картки замовлення #{order.id} у чат {target_chat_id}: {send_err}")
        return None


# ================= ОБРОБНИК НАТИСКАНЬ КНОПОК ПІДРОЗДІЛІВ У ШТАБНОМУ ЧАТІ =================

ACTION_REQUIRED_ROLE: Dict[str, Tuple[str, str]] = {
    "traffic_ok": ("traffic_service", "Служба руху"),
    "add_slots": ("traffic_service", "Служба руху"),
    "legal_ok": ("legal_dept", "Юридичний відділ"),
    "vuptap_ok": ("vuptap_dept", "ВУПтаП"),
    "acc_ok": ("accounting_dept", "Бухгалтерія"),
    "depot_assign": ("depot_tram", "Депо"),
    "complete": ("traffic_service", "Служба руху"),
    "cancel": ("traffic_service", "Служба руху"),
}


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
    user = update.effective_user
    user_id = user.id
    actor_name = user.full_name or user.username or str(user_id)

    order = await db.get_rental_order(order_id)
    if not order:
        await query.answer("❌ Замовлення не знайдено в базі даних.", show_alert=True)
        return

    # 1. Перевірка ролі підрозділу (RBAC)
    req_role_key, role_label = ACTION_REQUIRED_ROLE.get(action, ("traffic_service", "Штаб"))
    if action == "depot_assign":
        if order.transport_type == "TROLLEYBUS":
            allowed = has_staff_role(user_id, "depot_trolley") or has_staff_role(user_id, "depot_tram")
            role_label = "Тролейбусне депо"
        else:
            allowed = has_staff_role(user_id, "depot_tram")
            role_label = f"Депо {order.depot_code}"
    else:
        allowed = has_staff_role(user_id, req_role_key)

    if not allowed:
        await query.answer(
            f"⛔ Доступ обмежено! Ця кнопка призначена виключно для підрозділу «{role_label}».",
            show_alert=True,
        )
        return

    # 2. Двоетапний захист від випадкового натискання (протягом 10 секунд)
    if not check_two_step_confirmation(user_id, order_id, action):
        await query.answer(
            f"⚠️ Підтвердження дії ({role_label}):\n"
            f"Натисніть цю саму кнопку ЩЕ РАЗ протягом 10 секунд, щоб підтвердити дію за договором №{order.contract_number}.",
            show_alert=True,
        )
        return

    now_dt = datetime.datetime.now()

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
            actor_role="Служба руху",
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
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🕒 <b>Додавання вільних слотів у пул на дату {order.rental_date}</b> (для Договору №{order.contract_number}):\n\n"
                f"Напишіть у відповідь вільні години подачі через кому (наприклад: <code>11:00, 14:00, 16:30</code>).\n"
                f"<i>Усі додані слоти збережуться в базі: коли перший клієнт обере один слот, решта залишаться доступними для наступних клієнтів!</i>"
            ),
            parse_mode=ParseMode.HTML,
        )
        return

    if action == "legal_ok":
        new_status = order.status
        if order.status in ("awaiting_signature", "signed_uploaded"):
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
            actor_role="Юридичний відділ",
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
            actor_role="ВУПтаП",
            action="VUPTAP_APPROVED",
            details="Погоджено умови безпеки дорожнього руху та інструктаж",
        )
        await query.answer("✅ ВУПтаП погодив безпеку руху!")
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
            actor_role="Бухгалтерія",
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
        _PENDING_STAFF_INPUT[(chat_id, user_id)] = {
            "mode": "depot",
            "order_id": order.id,
        }
        await query.answer("Введіть бортовий номер та ПІБ водія у чат")
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🚋 <b>Призначення рухомого складу та водія ({order.depot_code}) для Договору №{order.contract_number}:</b>\n\n"
                f"Надішліть одним повідомленням через кому:\n"
                f"<code>Бортовий №, ПІБ водія, Телефон водія</code>\n"
                f"Наприклад: <code>914, Коваленко Олександр Петрович, +380501112233</code>"
            ),
            parse_mode=ParseMode.HTML,
        )
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
    1) Очікуваний ввід часових слотів ('12:00, 15:00') від Служби руху;
    2) Очікуваний ввід бортового номера та водія ('914, Коваленко О.П., +380...') від Депо;
    3) Reply на картку замовлення з префіксом 'Коментар: ...' або 'Інфо: ...' для клієнта.
    Повертає True, якщо повідомлення було оброблено.
    """
    msg = update.message
    if not msg or not msg.text or not update.effective_user or not update.effective_chat:
        return False

    chat_id = update.effective_chat.id
    user = update.effective_user
    user_id = user.id
    actor_name = user.full_name or user.username or str(user_id)
    text = msg.text.strip()

    # 1. Перевіряємо активний режим вводу (слоти або призначення депо)
    pending = _PENDING_STAFF_INPUT.get((chat_id, user_id))
    if pending:
        mode = pending.get("mode")
        order_id = int(pending["order_id"])
        order = await db.get_rental_order(order_id)
        del _PENDING_STAFF_INPUT[(chat_id, user_id)]

        if not order:
            await msg.reply_text("❌ Замовлення не знайдено.")
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
                actor_role="Служба руху",
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
                actor_role=f"Депо {order.depot_code}",
                action="VEHICLE_ASSIGNED",
                details=f"Призначено борт №{board_num}, водій: {driver_name} ({driver_phone})",
            )
            await post_or_update_staff_order_card(context, order.id)

            # Генеруємо та надсилаємо клієнту електронний посадковий талон із QR-кодом
            if updated_order:
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
                                f"📅 <b>Подача на кільце «{updated_order.pickup_stop}»:</b> {updated_order.rental_date} о {updated_order.rental_time_slot}\n\n"
                                f"Покажіть цей талон або QR-код водієві під час посадки на розворотному кільці. Гарної поїздки!"
                            ),
                            parse_mode=ParseMode.HTML,
                        )
                except Exception as send_err:
                    logger.warning(f"Не вдалося надіслати посадковий талон клієнту: {send_err}")

            await msg.reply_text(
                f"✅ Борт <b>№{board_num}</b> та водія <b>{driver_name}</b> призначено! "
                f"Клієнту автоматично надіслано електронний посадковий талон із QR-кодом.",
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
                    await db.add_rental_audit_log(
                        order_id=order.id,
                        actor_id=user_id,
                        actor_name=actor_name,
                        actor_role="Повідомлення штабу",
                        action="STAFF_COMMENT",
                        details=f"Коментар клієнту: {comment_body}",
                    )
                    await post_or_update_staff_order_card(context, order.id)
                    try:
                        await context.bot.send_message(
                            chat_id=order.user_id,
                            text=(
                                f"💬 <b>Офіційне повідомлення від КП «Одесміськелектротранс»</b>\n"
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
