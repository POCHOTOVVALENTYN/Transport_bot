"""
Клієнтські обробники модуля «🚋 Оренда та екскурсії (Трамвай / Тролейбус)»
для КП «Одесміськелектротранс».
Доступ до розділу суворо контролюється функцією `is_rental_access_allowed`
(наразі відкритий виключно для Валентина — ID 830196453).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from bot.states import States
from config.settings import (
    RENTAL_IBAN_ACCOUNT,
    RENTAL_IBAN_COMPANY_ADDRESS,
    RENTAL_IBAN_COMPANY_NAME,
    RENTAL_IBAN_EDRPOU,
    RENTAL_MIN_DAYS_KEP,
    RENTAL_MIN_DAYS_PAPER,
    RENTAL_PAPER_LOCK_HOURS,
    RENTAL_RETRO_HUB_IMAGE,
)
from database.db import Database, RentalOrder
from handlers.rental_staff_handlers import (
    STATUS_LABELS_UA,
    get_active_staff_chat_id,
    get_staff_topic_thread_id,
    is_rental_access_allowed,
    post_or_update_staff_order_card,
)
from services.rental_documents_service import (
    RENTAL_EXTRA_SERVICES,
    RENTAL_POPULAR_PRESETS,
    RENTAL_WAGON_CATALOG,
    RentalPriceInput,
    build_nbu_iban_payment_purpose,
    calculate_rental_price_breakdown,
    format_money_ua,
    generate_rental_boarding_pass_pdf,
    generate_rental_contract_docx,
    generate_rental_contract_pdf,
    generate_rental_iban_invoice_pdf,
    send_legal_contract_email,
)
from services.tram_rental_service import (
    POPULAR_TRAM_STOPS,
    RentalCalculationInput,
    calculate_rental_route,
    generate_rental_route_sheet_pdf,
    get_all_districts,
    get_all_rental_points,
    get_available_turning_loops,
    get_stop_directional_options,
    get_stops_by_district,
    is_turnaround_loop,
    search_tram_stops,
)
from utils.logger import logger

db = Database()

LOOPS_PAGE_SIZE = 10


def _get_draft(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
    return context.user_data.setdefault("rental_draft", {})


def _reset_draft(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
    context.user_data["rental_draft"] = {
        "wagon_key": "retro_mtv",
        "transport_type": "TRAM",
        "engine_wagon_type": "retro",
        "depot_code": "ВРМ",
        "route_mode": "preset",
        "preset_name": None,
        "pickup_stop": "пл. Старосінна",
        "via_loops": ["Аркадія"],
        "dropoff_stop": "пл. Старосінна",
        "wait_minutes": 5,
        "extra_services": [],
        "signing_scenario": "kep",
        "rental_date": None,
        "rental_time_slot": None,
        "customer_type": "individual",
        "user_full_name": None,
        "user_phone": None,
        "user_tax_id": None,
    }
    return context.user_data["rental_draft"]


async def _send_or_edit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    """
    Розумне оновлення екрану (Single-screen UI) для збереження чистоти чату:
    1. Видаляє залишки старих медіа / фото, якщо користувач перейшов у текстовий розділ,
    2. При натисканні інлайн-кнопок редагує існуюче повідомлення,
    3. При текстовому вводі (ПІБ, телефон, дата тощо) миттєво видаляє повідомлення користувача
       та редагує попереднє повідомлення бота, уникаючи розростання чату.
    """
    chat_id = update.effective_chat.id if update.effective_chat else None
    query = update.callback_query

    # Очищуємо старі фото з чату (наприклад, титульну картку ретро-трамвая)
    media_ids = context.user_data.pop("media_message_ids", None)
    if media_ids and chat_id:
        for mid in media_ids:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass

    if query:
        try:
            await query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
            context.user_data["last_bot_msg_id"] = query.message.message_id
            return
        except Exception:
            pass

        try:
            await query.message.delete()
        except Exception:
            pass

        if chat_id:
            sent = await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
            context.user_data["last_bot_msg_id"] = sent.message_id
        return

    # Якщо користувач надіслав текстове повідомлення або документ
    if update.message and chat_id:
        try:
            await update.message.delete()
        except Exception:
            pass

        prev_id = context.user_data.get("last_bot_msg_id")
        if prev_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=prev_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML,
                )
                return
            except Exception:
                pass

        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )
        context.user_data["last_bot_msg_id"] = sent.message_id


async def _send_or_edit_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    photo_path: str | Path,
    caption: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    """Надсилає або оновлює фотографію з підписом та клавіатурою для титульних розділів з контролем чистоти чату."""
    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else None

    # Очищуємо попередні медіа, якщо збереглися
    media_ids = context.user_data.pop("media_message_ids", None)
    if media_ids and chat_id:
        for mid in media_ids:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass

    if os.path.exists(str(photo_path)) and chat_id:
        if query and query.message:
            if query.message.photo:
                try:
                    await query.edit_message_caption(
                        caption=caption,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.HTML,
                    )
                    context.user_data["media_message_ids"] = [query.message.message_id]
                    context.user_data["last_bot_msg_id"] = query.message.message_id
                    return
                except Exception:
                    pass
            try:
                await query.message.delete()
            except Exception:
                pass

        with open(str(photo_path), "rb") as f_photo:
            sent_msg = await context.bot.send_photo(
                chat_id=chat_id,
                photo=f_photo,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
            context.user_data["media_message_ids"] = [sent_msg.message_id]
            context.user_data["last_bot_msg_id"] = sent_msg.message_id
        return

    await _send_or_edit(update, context, caption, reply_markup)


# ================= 1. ГОЛОВНИЙ ХАБ РОЗДІЛУ ОРЕНДИ =================

async def show_rental_hub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Головне меню розділу '🚋 Оренда електротранспорту' (доступне тільки Валентину)."""
    user = update.effective_user
    if not user or not is_rental_access_allowed(user.id):
        if update.callback_query:
            await update.callback_query.answer("🔒 Розділ перебуває в режимі закритого тестування.", show_alert=True)
        return ConversationHandler.END

    if update.callback_query:
        await update.callback_query.answer()

    active_orders = await db.get_user_active_rental_orders(user.id)
    contracts_badge = f" ({len(active_orders)})" if active_orders else ""

    text = (
        "🚋 <b>ОРЕНДА ЕЛЕКТРОТРАНСПОРТУ КП «ОМЕТ»</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Точний розрахунок.\n"
        "✅ Безпека руху.\n"
        "✅ Доступні формати договору: електронний (Дія.Підпис / КЕП) або паперовий в Управлінні КП.\n"
        "✅ Офіційна та зручна оплата IBAN."
    )

    keyboard = [
        [InlineKeyboardButton("🚋 Оформити замовлення", callback_data="rental_start_wizard")],
        [
            InlineKeyboardButton(
                f"📂 Діючі договори та замовлення{contracts_badge}",
                callback_data="rental_my_contracts",
            )
        ],
        [InlineKeyboardButton("📋 Правила оренди та тарифи", callback_data="rental_rules_info")],
        [InlineKeyboardButton("⬅️ Назад (Про підприємство)", callback_data="company_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")],
    ]
    await _send_or_edit_photo(update, context, RENTAL_RETRO_HUB_IMAGE, text, InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END


async def show_rental_rules_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Довідка про правила розрахунку Wialon, розворотні кільця та два сценарії договору."""
    query = update.callback_query
    if query:
        await query.answer()
    if not update.effective_user or not is_rental_access_allowed(update.effective_user.id):
        return

    text = (
        "📋 <b>ПРАВИЛА ОРЕНДИ ТА ТАРИФИ КП «ОМЕТ»</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ <b>Як розраховується орендний час за телеметрією Wialon:</b>\n"
        "• <b>Фаза 1 (Подача):</b> виїзд вагона з депо ВРМ до розворотного кільця посадки.\n"
        "• <b>Фаза 2 (Орендний рейс):</b> рух у загальному потоці трамвайної мережі Одеси + час узгодженої стоянки на кільцях.\n"
        "• <b>Фаза 3 (Заїзд):</b> повернення вагона від кільця висадки у депо ВРМ.\n"
        "• База нарахування — <b>загальний час зайнятості вагона від виїзду з депо до повернення</b>: max(60, Час Wialon) × 72,30 грн.\n\n"
        "2️⃣ <b>Чому посадка здійснюється на розворотних кільцях:</b>\n"
        "Щоб не затримувати регулярний рух міських трамваїв на лінійних зупинках, "
        "посадка пасажирів, святкове оформлення, фотозупинки та висадка проводяться виключно на офіційних розворотних кільцях міста.\n\n"
        "3️⃣ <b>Два варіанти підписання договору:</b>\n"
        "• 📱 <b>Електронний договір (Дія.Підпис / КЕП .p7s):</b> замовлення щонайменше за <b>3 дні</b> до рейсу.\n"
        "• 🏢 <b>Паперовий договір в Управлінні КП (вул. Водопровідна, 1):</b> замовлення щонайменше за <b>4 дні</b> до рейсу (бронь слоту діє <b>36 годин</b>).\n\n"
        "4️⃣ <b>Офіційна безготівкова оплата IBAN:</b>\n"
        "Оплата на рахунок КП «ОМЕТ» за офіційним стандартом QR-коду НБУ з обов'язковим призначенням платежу «у т.ч. ПДВ 20%»."
    )
    keyboard = [
        [InlineKeyboardButton("🚋 Оформити замовлення", callback_data="rental_start_wizard")],
        [InlineKeyboardButton("⬅️ Назад у меню оренди", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, text, InlineKeyboardMarkup(keyboard))


# ================= 2. КРОК 1: ВИБІР РУХОМОГО СКЛАДУ =================

async def rental_start_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
    if not update.effective_user or not is_rental_access_allowed(update.effective_user.id):
        return ConversationHandler.END

    _reset_draft(context)

    text = (
        "🚊 <b>КРОК 1 із 6 — РУХОМИЙ СКЛАД</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "• <b>🚋 Ретро-трамвай МТВ-82 / Відкритий №914</b>\n"
        "  Місць: до 40 |\n"
        "  Мінімальне замовлення: 1 година (60 хв)\n"
        "  Історичний екскурсійний трамвай для свят, фотосесій та прогулянок Одесою.\n\n"
        "☀️ <i>Зверніть увагу: відкритий ретро-вагон №914 не має бокового засклення та опалення, "
        "тому рекомендований для замовлення у теплий сезон (весна/літо).</i>\n\n"
        "Оберіть бажаний вагон:"
    )
    buttons = [
        [InlineKeyboardButton("🚋 Ретро-трамвай МТВ-82 (закритий салон)", callback_data="rental_wagon:retro_mtv")],
        [InlineKeyboardButton("☀️ Відкритий ретро-вагон №914 (літній)", callback_data="rental_wagon:retro_914")],
        [InlineKeyboardButton("⬅️ Скасувати / Назад", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, text, InlineKeyboardMarkup(buttons))
    return States.RENTAL_SELECT_WAGON


async def rental_select_wagon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    w_key = query.data.split(":", 1)[1]
    w_info = RENTAL_WAGON_CATALOG.get(w_key) or RENTAL_WAGON_CATALOG["retro_mtv"]

    draft = _get_draft(context)
    draft["wagon_key"] = w_key
    draft["wagon_title"] = w_info["short_title"]
    draft["transport_type"] = w_info["transport_type"]
    draft["engine_wagon_type"] = w_info["engine_wagon_type"]
    draft["depot_code"] = w_info["default_depot"]

    return await _prompt_route_mode(update, context)


async def _prompt_route_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = _get_draft(context)
    text = (
        f"🗺️ <b>КРОК 2 із 6 — ВИБІР МАРШРУТУ (Трамвайна мережа)</b>\n"
        f"Обраний транспорт: <b>{draft.get('wagon_title')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Оберіть спосіб побудови маршруту:\n\n"
        f"🌟 <b>Режим А — Популярні готові ретро-маршрути:</b> перевірені екскурсійні маршрути Одесою "
        f"(Аркадія, Парк Шевченка, Великий Фонтан, Хаджибейський лиман).\n"
        f"🛠️ <b>Режим Б — Конструктор за розворотними кільцями:</b> самостійно оберіть розворотне кільце посадки, "
        f"будь-яку кількість проміжних розворотних кілець та кільце висадки пасажирів."
    )
    keyboard = [
        [InlineKeyboardButton("🌟 Режим А: Популярні готові маршрути", callback_data="rental_rmode:preset")],
        [InlineKeyboardButton("🛠️ Режим Б: Власний маршрут по кільцях", callback_data="rental_rmode:custom")],
        [InlineKeyboardButton("⬅️ Назад до вибору вагона", callback_data="rental_start_wizard")],
    ]
    await _send_or_edit(update, context, text, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_SELECT_ROUTE_MODE


# ================= 3. КРОК 2А / 2Б: ПОПУЛЯРНІ МАРШРУТИ АБО КОНСТРУКТОР КІЛЕЦЬ =================

async def rental_select_route_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    mode = query.data.split(":", 1)[1]
    draft = _get_draft(context)
    draft["route_mode"] = mode

    if mode == "preset":
        vt = draft["transport_type"]
        matching_presets = [
            p for p in RENTAL_POPULAR_PRESETS.values() if p["transport_type"] == vt
        ]
        if not matching_presets:
            matching_presets = list(RENTAL_POPULAR_PRESETS.values())

        text = (
            "🌟 <b>ПОПУЛЯРНІ ЕКСКУРСІЙНІ МАРШРУТИ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Оберіть готовий маршрут (посадка, розвороти та висадка відбуваються на офіційних розворотних кільцях):\n"
        )
        buttons: List[List[InlineKeyboardButton]] = []
        for p in matching_presets:
            buttons.append(
                [InlineKeyboardButton(p["title"], callback_data=f"rental_preset:{p['key']}")]
            )
        buttons.append([InlineKeyboardButton("🛠️ Перейти у власний конструктор кілець", callback_data="rental_rmode:custom")])
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="rental_back_rmode")])
        await _send_or_edit(update, context, text, InlineKeyboardMarkup(buttons))
        return States.RENTAL_SELECT_PRESET

    # Режим Б: Власний конструктор маршруту (будь-яка зупинка або кільце міста)
    draft["via_loops"] = []
    return await _render_stop_selection_hub(update, context, step="pickup")


async def rental_select_preset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    p_key = query.data.split(":", 1)[1]
    preset = RENTAL_POPULAR_PRESETS.get(p_key)
    if not preset:
        return await _prompt_route_mode(update, context)

    draft = _get_draft(context)
    draft["preset_name"] = preset["title"]
    draft["pickup_stop"] = preset["pickup_stop"]
    draft["via_loops"] = list(preset["via_loops"])
    draft["dropoff_stop"] = preset["dropoff_stop"]
    draft["wait_minutes"] = int(preset["recommended_wait_min"])

    return await _prompt_wait_time(update, context)


POPULAR_PAGE_SIZE = 10


async def _render_stop_selection_hub(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    step: str = "pickup",
    error_msg: Optional[str] = None,
) -> int:
    """
    Головний екран конструктора маршруту для вибору точки (початкової, проміжних кілець чи кінцевої).
    """
    draft = _get_draft(context)
    context.user_data["rental_stop_step"] = step

    if step == "pickup":
        header = (
            "🟢 <b>КОНСТРУКТОР: ПОЧАТКОВА ЗУПИНКА ОРЕНДНОГО МАРШРУТУ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Ви можете обрати будь-яку трамвайну зупинку Одеси або розворотне кільце:\n"
            "• <i>Ретро-трамвай прибуває завчасно та очікує у межах технологічного інтервалу руху (очікування перед стартом не тарифікується).</i>\n\n"
            "Оберіть зручний спосіб вибору початкової зупинки:"
        )
        target_state = States.RENTAL_SELECT_PICKUP_LOOP
        back_btn = InlineKeyboardButton("⬅️ Назад до вибору режиму", callback_data="rental_back_rmode")
        keyboard = [
            [InlineKeyboardButton("⭐ Популярні зупинки (ТОП-20)", callback_data="rental_stop_pop:pickup:0")],
            [InlineKeyboardButton("🔍 Швидкий пошук за назвою", callback_data="rental_stop_search_prompt:pickup")],
            [InlineKeyboardButton("📍 Обрати за районами міста", callback_data="rental_stop_districts:pickup")],
            [back_btn],
        ]
    elif step == "via":
        chosen_via = draft.get("via_loops", [])
        pickup_title = draft.get("pickup_direction") or draft.get("pickup_stop", "Початкова")
        via_chain = " ➡️ ".join([f"🟢 {pickup_title}"] + [f"🔄 {v}" for v in chosen_via])
        header = (
            "🔄 <b>КОНСТРУКТОР: ПРОМІЖНІ ЗУПИНКИ ТА КІЛЬЦЯ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"Поточна нитка маршруту:\n<b>{via_chain}</b>\n\n"
            "Додайте ще одне кільце або перейдіть до вибору кінцевої зупинки орендного маршруту:"
        )
        target_state = States.RENTAL_SELECT_VIA_LOOPS
        back_btn = InlineKeyboardButton("⬅️ Назад до початкової зупинки", callback_data="rental_back_pickup")
        keyboard = [
            [InlineKeyboardButton("🔍 Швидкий пошук за назвою", callback_data="rental_stop_search_prompt:via")],
            [InlineKeyboardButton("🏁 Обрати кінцеву зупинку маршруту", callback_data="rental_via_done")],
        ]
        if draft.get("via_loops"):
            keyboard.append([InlineKeyboardButton("🗑️ Очистити проміжні зупинки", callback_data="rental_via_clear")])
        keyboard.append([back_btn])
    else:  # dropoff
        chosen_via = draft.get("via_loops", [])
        pickup_title = draft.get("pickup_direction") or draft.get("pickup_stop", "Початкова")
        via_chain = " ➡️ ".join([f"🟢 {pickup_title}"] + [f"🔄 {v}" for v in chosen_via])
        header = (
            "🏁 <b>КОНСТРУКТОР: КІНЦЕВА ЗУПИНКА ОРЕНДНОГО МАРШРУТУ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"Поточна нитка маршруту:\n<b>{via_chain} ➡️ [Кінцева зупинка]</b>\n\n"
            "Оберіть кінцеву зупинку орендного рейсу:"
        )
        target_state = States.RENTAL_SELECT_DROPOFF_LOOP
        back_btn = InlineKeyboardButton("⬅️ Назад до проміжних точок", callback_data="rental_back_via")
        keyboard = [
            [InlineKeyboardButton("🔍 Швидкий пошук за назвою", callback_data="rental_stop_search_prompt:dropoff")],
            [back_btn],
        ]

    if error_msg:
        header = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + header

    await _send_or_edit(update, context, header, InlineKeyboardMarkup(keyboard))
    return target_state


async def _render_popular_stops_picker(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    step: str,
    page: int = 0,
) -> int:
    """Відображає ТОП-20 популярних зупинок Одеси з пагінацією по 10 штук (по 2 в ряд)."""
    draft = _get_draft(context)
    vt = draft.get("transport_type", "TRAM")
    all_pts = get_all_rental_points(vt)
    total_pages = max(1, (len(POPULAR_TRAM_STOPS) + POPULAR_PAGE_SIZE - 1) // POPULAR_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start_idx = page * POPULAR_PAGE_SIZE
    page_items = POPULAR_TRAM_STOPS[start_idx : start_idx + POPULAR_PAGE_SIZE]

    step_labels = {
        "pickup": "посадки",
        "via": "проміжної точки",
        "dropoff": "висадки",
    }
    step_label = step_labels.get(step, "посадки")
    header = (
        f"⭐ <b>ПОПУЛЯРНІ ТА ЕКСКУРСІЙНІ ЗУПИНКИ: ТОЧКА {step_label.upper()}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>🔄 — розворотне кільце (можлива стоянка до 10 хв)\n"
        "🚏 — лінійна зупинка (посадка/висадка в межах інтервалу руху)</i>\n\n"
        f"Сторінка {page + 1}/{total_pages}. Оберіть зупинку:"
    )

    buttons: List[List[InlineKeyboardButton]] = []
    for i in range(0, len(page_items), 2):
        row: List[InlineKeyboardButton] = []
        for j in range(2):
            if i + j < len(page_items):
                item = page_items[i + j]
                name = item["name"]
                icon = item["icon"]
                idx = all_pts.index(name) if name in all_pts else 0
                row.append(
                    InlineKeyboardButton(
                        f"{icon} {name}",
                        callback_data=f"rental_spick:{step}:{idx}",
                    )
                )
        buttons.append(row)

    nav_row: List[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Попер.", callback_data=f"rental_stop_pop:{step}:{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Наст. ➡️", callback_data=f"rental_stop_pop:{step}:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton("⬅️ До способів вибору", callback_data=f"rental_stop_hub:{step}")])
    await _send_or_edit(update, context, header, InlineKeyboardMarkup(buttons))

    if step == "pickup":
        return States.RENTAL_SELECT_PICKUP_LOOP
    if step == "via":
        return States.RENTAL_SELECT_VIA_LOOPS
    return States.RENTAL_SELECT_DROPOFF_LOOP


async def _render_districts_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    step: str,
) -> int:
    """Відображає перелік 6 районів Одеси для вибору зупинки."""
    districts = get_all_districts()
    step_labels = {"pickup": "посадки", "via": "проміжної точки", "dropoff": "висадки"}
    header = (
        f"📍 <b>ОБЕРІТЬ РАЙОН МІСТА ДЛЯ ТОЧКИ {step_labels.get(step, 'посадки').upper()}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Оберіть район, щоб переглянути зупинки трамвайної лінії:"
    )
    buttons: List[List[InlineKeyboardButton]] = []
    for d_idx, d_name in enumerate(districts):
        buttons.append([InlineKeyboardButton(d_name, callback_data=f"rental_stop_dist:{step}:{d_idx}")])
    buttons.append([InlineKeyboardButton("⬅️ До способів вибору", callback_data=f"rental_stop_hub:{step}")])
    await _send_or_edit(update, context, header, InlineKeyboardMarkup(buttons))

    if step == "pickup":
        return States.RENTAL_SELECT_PICKUP_LOOP
    if step == "via":
        return States.RENTAL_SELECT_VIA_LOOPS
    return States.RENTAL_SELECT_DROPOFF_LOOP


async def _render_district_stops(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    step: str,
    district_idx: int,
) -> int:
    """Відображає перелік зупинок для обраного району міста."""
    draft = _get_draft(context)
    vt = draft.get("transport_type", "TRAM")
    all_pts = get_all_rental_points(vt)
    districts = get_all_districts()
    d_name = districts[district_idx] if 0 <= district_idx < len(districts) else districts[0]
    d_stops = get_stops_by_district(d_name)

    header = (
        f"📍 <b>ЗУПИНКИ РАЙОНУ: {d_name}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>🔄 — розворотне кільце | 🚏 — лінійна зупинка</i>\n\n"
        "Оберіть зупинку зі списку:"
    )
    buttons: List[List[InlineKeyboardButton]] = []
    for i in range(0, len(d_stops), 2):
        row: List[InlineKeyboardButton] = []
        for j in range(2):
            if i + j < len(d_stops):
                stop_name = d_stops[i + j]
                icon = "🔄" if is_turnaround_loop(stop_name, vt) else "🚏"
                idx = all_pts.index(stop_name) if stop_name in all_pts else 0
                row.append(
                    InlineKeyboardButton(
                        f"{icon} {stop_name}",
                        callback_data=f"rental_spick:{step}:{idx}",
                    )
                )
        buttons.append(row)

    buttons.append([InlineKeyboardButton("⬅️ До вибору районів", callback_data=f"rental_stop_districts:{step}")])
    buttons.append([InlineKeyboardButton("🏠 До способів вибору", callback_data=f"rental_stop_hub:{step}")])
    await _send_or_edit(update, context, header, InlineKeyboardMarkup(buttons))

    if step == "pickup":
        return States.RENTAL_SELECT_PICKUP_LOOP
    if step == "via":
        return States.RENTAL_SELECT_VIA_LOOPS
    return States.RENTAL_SELECT_DROPOFF_LOOP


async def _render_stop_search_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    step: str,
    error_msg: Optional[str] = None,
) -> int:
    """Відображає екран готовності до текстового пошуку зупинки за назвою."""
    context.user_data["rental_stop_step"] = step
    step_labels = {"pickup": "посадки", "via": "проміжної точки", "dropoff": "висадки"}
    header = (
        f"🔍 <b>ШВИДКИЙ ПОШУК ЗУПИНКИ {step_labels.get(step, 'посадки').upper()}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Надішліть сюди у чат повідомлення з назвою або частиною назви зупинки:\n"
        "<i>Наприклад: <b>Канатна</b>, <b>Грецька</b>, <b>Філатова</b>, <b>Дерибасівська</b>, <b>Аркадія</b>, <b>Торгова</b></i>"
    )
    if error_msg:
        header = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + header

    keyboard = [[InlineKeyboardButton("⬅️ До способів вибору", callback_data=f"rental_stop_hub:{step}")]]
    await _send_or_edit(update, context, header, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_SEARCH_STOP_TEXT


async def _render_stop_direction_picker(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    step: str,
    idx: int,
    stop_name: str,
    options: List[Dict[str, Any]],
) -> int:
    """Відображає вибір напрямку руху колії для двосторонньої зупинки."""
    header = (
        f"🚏 <b>НАПРЯМОК РУХУ: {stop_name}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Ця зупинка має кілька посадкових платформ для різних напрямків колії.\n"
        "Оберіть потрібний напрямок руху:"
    )
    buttons: List[List[InlineKeyboardButton]] = []
    for opt in options:
        pid = opt.get("platform_id", "")
        d_name = opt.get("display_name", stop_name)
        buttons.append([
            InlineKeyboardButton(
                f"🚏 {d_name}",
                callback_data=f"rental_spick:{step}:{idx}:{pid}",
            )
        ])
    buttons.append([InlineKeyboardButton("⬅️ Скасувати вибір", callback_data=f"rental_stop_hub:{step}")])
    await _send_or_edit(update, context, header, InlineKeyboardMarkup(buttons))
    if step == "pickup":
        return States.RENTAL_SELECT_PICKUP_LOOP
    if step == "via":
        return States.RENTAL_SELECT_VIA_LOOPS
    return States.RENTAL_SELECT_DROPOFF_LOOP


async def rental_handle_stop_search_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє текстовий пошук зупинки від замовника з збереженням чистоти чату та врахуванням напрямку."""
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_SEARCH_STOP_TEXT

    query_text = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    step = context.user_data.get("rental_stop_step", "pickup")
    draft = _get_draft(context)
    vt = draft.get("transport_type", "TRAM")
    all_pts = get_all_rental_points(vt)
    matches = search_tram_stops(query_text, transport_type=vt, limit=5)

    if not matches:
        return await _render_stop_search_prompt(
            update,
            context,
            step=step,
            error_msg=f"За запитом «{query_text}» зупинок не знайдено. Спробуйте інше слово або частину назви:",
        )

    header = (
        f"🔍 <b>РЕЗУЛЬТАТИ ПОШУКУ ДЛЯ «{query_text}»:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Оберіть потрібну зупинку та напрямок руху:\n"
        "<i>🔄 — розворотне кільце | 🚏 — лінійна зупинка</i>"
    )
    buttons: List[List[InlineKeyboardButton]] = []
    for match in matches:
        icon = "🔄" if is_turnaround_loop(match, vt) else "🚏"
        idx = all_pts.index(match) if match in all_pts else 0
        dir_options = get_stop_directional_options(match, vt)
        for opt in dir_options:
            pid = opt.get("platform_id", "")
            d_title = opt.get("display_name", match)
            buttons.append([
                InlineKeyboardButton(
                    f"{icon} {d_title}",
                    callback_data=f"rental_spick:{step}:{idx}:{pid}",
                )
            ])
            if len(buttons) >= 8:
                break
        if len(buttons) >= 8:
            break

    buttons.append([InlineKeyboardButton("🔍 Шукати іншу назву", callback_data=f"rental_stop_search_prompt:{step}")])
    buttons.append([InlineKeyboardButton("⬅️ До способів вибору", callback_data=f"rental_stop_hub:{step}")])

    await _send_or_edit(update, context, header, InlineKeyboardMarkup(buttons))
    if step == "pickup":
        return States.RENTAL_SELECT_PICKUP_LOOP
    if step == "via":
        return States.RENTAL_SELECT_VIA_LOOPS
    return States.RENTAL_SELECT_DROPOFF_LOOP


async def rental_handle_stop_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Фіксує обрану зупинку з напрямком руху та спрямовує на наступний крок."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    step = parts[1]
    idx = int(parts[2])
    pid = parts[3] if len(parts) > 3 else ""

    draft = _get_draft(context)
    vt = draft.get("transport_type", "TRAM")
    all_pts = get_all_rental_points(vt)
    chosen_stop = all_pts[idx] if 0 <= idx < len(all_pts) else all_pts[0]

    # Якщо напрямок не був вказаний у callback і зупинка має кілька платформ — пропонуємо обрати напрямок
    if not pid:
        dir_options = get_stop_directional_options(chosen_stop, vt)
        if len(dir_options) > 1:
            return await _render_stop_direction_picker(update, context, step, idx, chosen_stop, dir_options)

    # Визначаємо підпис напрямку руху
    chosen_direction_label = ""
    if pid:
        for opt in get_stop_directional_options(chosen_stop, vt):
            if opt.get("platform_id") == pid:
                chosen_direction_label = opt.get("direction", "")
                break

    if step == "pickup":
        draft["pickup_stop"] = chosen_stop
        draft["pickup_platform_id"] = pid
        draft["pickup_direction"] = f"{chosen_stop} ({chosen_direction_label})" if chosen_direction_label else chosen_stop
        draft["via_loops"] = []
        draft["via_points"] = []
        return await _render_stop_selection_hub(update, context, step="via")

    elif step == "via":
        context.user_data["rental_pending_via"] = {
            "stop_name": chosen_stop,
            "platform_id": pid,
            "direction": chosen_direction_label,
        }
        return await _render_via_alighting_prompt(update, context)

    else:  # dropoff
        draft["dropoff_stop"] = chosen_stop
        draft["dropoff_platform_id"] = pid
        if draft.get("pickup_stop") == draft.get("dropoff_stop") and not draft.get("via_loops"):
            await query.answer(
                "Для кільцевого маршруту (посадка і кінцева на одній зупинці) оберіть хоча б одне проміжне розворотне кільце!",
                show_alert=True,
            )
            return await _render_stop_selection_hub(update, context, step="via")
        return await _render_route_dashboard(update, context)


async def _render_via_alighting_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Запитує у клієнта, чи планується проміжна висадка пасажирів на обраному кільці."""
    pending = context.user_data.get("rental_pending_via", {})
    stop_name = pending.get("stop_name", "Обране кільце")
    text = (
        f"🔄 <b>ПРОМІЖНЕ КІЛЬЦЕ: {stop_name}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Чи планується на цьому розворотному кільці проміжна висадка пасажирів (фотосесія, прогулянка алеєю)?\n"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ Так, висадка / прогулянка", callback_data="rental_via_alight:yes"),
            InlineKeyboardButton("❌ Ні, лише технічний розворот", callback_data="rental_via_alight:no"),
        ],
        [InlineKeyboardButton("⬅️ Скасувати вибір точки", callback_data="rental_via_alight:cancel")],
    ]
    await _send_or_edit(update, context, text, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_VIA_PROMPT_DROPOFF


async def rental_handle_via_alighting_selected(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Обробляє відповідь щодо висадки пасажирів на проміжному кільці."""
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "rental_via_alight:cancel":
        context.user_data.pop("rental_pending_via", None)
        return await _render_stop_selection_hub(update, context, step="via")

    choice = data.split(":", 1)[1]
    pending = context.user_data.setdefault("rental_pending_via", {})
    pending["has_dropoff"] = (choice == "yes")
    return await _render_via_wait_prompt(update, context)


async def _render_via_wait_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Запитує час стоянки на кільці (максимум 10 хвилин)."""
    pending = context.user_data.get("rental_pending_via", {})
    stop_name = pending.get("stop_name", "Обране кільце")
    text = (
        f"⏱️ <b>ЧАС СТОЯНКИ: {stop_name}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Оберіть час стоянки вагона (максимум 10 хв, щоб не порушувати регулярний графік лінійних трамваїв):\n"
    )
    if error_msg:
        text = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + text

    keyboard = [
        [
            InlineKeyboardButton("⏱️ 0 хв", callback_data="rental_via_wait:0"),
            InlineKeyboardButton("⏱️ 2 хв", callback_data="rental_via_wait:2"),
            InlineKeyboardButton("⏱️ 5 хв", callback_data="rental_via_wait:5"),
        ],
        [
            InlineKeyboardButton("⏱️ 7 хв", callback_data="rental_via_wait:7"),
            InlineKeyboardButton("⏱️ 10 хв", callback_data="rental_via_wait:10"),
        ],
        [InlineKeyboardButton("⬅️ Назад до висадки", callback_data="rental_via_wait:back")],
    ]
    await _send_or_edit(update, context, text, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_VIA_PROMPT_WAIT_MINUTES


async def rental_handle_via_wait_selected(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Обробляє вибір часу стоянки з кнопок."""
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "rental_via_wait:back":
        return await _render_via_alighting_prompt(update, context)

    mins = int(data.split(":", 1)[1])
    return await _save_via_point_and_continue(update, context, mins)


async def rental_handle_via_wait_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Обробляє введення часу стоянки повідомленням у чат."""
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_VIA_PROMPT_WAIT_MINUTES
    raw = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    if not raw.isdigit():
        return await _render_via_wait_prompt(
            update,
            context,
            error_msg="Будь ласка, введіть число хвилин від 0 до 10.",
        )
    mins = int(raw)
    if mins < 0 or mins > 10:
        return await _render_via_wait_prompt(
            update,
            context,
            error_msg="Максимальний час стоянки — 10 хвилин (введіть від 0 до 10).",
        )
    return await _save_via_point_and_continue(update, context, mins)


async def _save_via_point_and_continue(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    wait_mins: int,
) -> int:
    """Фіксує параметри проміжної точки у draft та повертає до конструктора."""
    draft = _get_draft(context)
    pending = context.user_data.pop("rental_pending_via", {})
    stop_name = pending.get("stop_name", "")
    if stop_name:
        via_points = draft.setdefault("via_points", [])
        via_points.append({
            "stop_name": stop_name,
            "has_dropoff": pending.get("has_dropoff", False),
            "wait_minutes": wait_mins,
            "platform_id": pending.get("platform_id", ""),
            "direction": pending.get("direction", ""),
        })
        via_loops = draft.setdefault("via_loops", [])
        if not via_loops or via_loops[-1] != stop_name:
            via_loops.append(stop_name)

    draft["wait_minutes"] = sum(p.get("wait_minutes", 0) for p in draft.get("via_points", []))
    return await _render_stop_selection_hub(update, context, step="via")


async def _render_route_dashboard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """
    Екран 4: Дашборд перегляду та точкового редагування створеного маршруту.
    Дозволяє замовнику бачити повний ланцюжок і редагувати точки без повторного введення з нуля.
    """
    draft = _get_draft(context)
    pickup = draft.get("pickup_direction") or draft.get("pickup_stop", "Не обрано")
    dropoff = draft.get("dropoff_stop", "Не обрано")
    via_pts = draft.get("via_points", [])

    via_lines: list[str] = []
    if not via_pts and draft.get("via_loops"):
        for idx, v in enumerate(draft["via_loops"], 1):
            via_lines.append(f" {idx}. 🔄 <b>{v}</b>")
    elif via_pts:
        for idx, vp in enumerate(via_pts, 1):
            alight_str = "висадка: так" if vp.get("has_dropoff") else "висадка: ні"
            w_str = f"стоянка: {vp.get('wait_minutes', 0)} хв"
            via_lines.append(f" {idx}. 🔄 <b>{vp['stop_name']}</b> ({alight_str}, {w_str})")

    via_text = "\n".join(via_lines) if via_lines else " <i>(прямий рейс без проміжних кілець)</i>"
    total_wait = sum(vp.get("wait_minutes", 0) for vp in via_pts) if via_pts else draft.get("wait_minutes", 0)
    draft["wait_minutes"] = total_wait

    text = (
        "🗺️ <b>ВАШ МАРШРУТ (РЕЖИМ ПЕРЕГЛЯДУ ТА РЕДАГУВАННЯ)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 <b>Початкова:</b> {pickup}\n\n"
        f"🔄 <b>Проміжні зупинки та кільця:</b>\n{via_text}\n\n"
        f"🏁 <b>Кінцева:</b> {dropoff}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ <b>Загальний час зупинок на кільцях:</b> {total_wait} хв (тарифікується)\n\n"
        "Ви можете затвердити маршрут або відкоригувати окремі точки:"
    )

    keyboard: list[list[InlineKeyboardButton]] = []
    if via_pts:
        del_row: list[InlineKeyboardButton] = []
        for i, vp in enumerate(via_pts):
            del_row.append(InlineKeyboardButton(f"❌ Прибрати №{i + 1}", callback_data=f"rental_dash_del:{i}"))
            if len(del_row) == 2:
                keyboard.append(del_row)
                del_row = []
        if del_row:
            keyboard.append(del_row)

    keyboard.append([
        InlineKeyboardButton("➕ Додати ще кільце", callback_data="rental_dash_add_via"),
        InlineKeyboardButton("✏️ Змінити кінцеву", callback_data="rental_dash_edit_dropoff"),
    ])
    keyboard.append([InlineKeyboardButton("✏️ Змінити початкову зупинку", callback_data="rental_dash_edit_pickup")])
    keyboard.append([InlineKeyboardButton("✅ Затвердити маршрут та перейти до дати", callback_data="rental_route_confirm")])
    keyboard.append([InlineKeyboardButton("🔄 Скинути маршрут і почати з нуля", callback_data="rental_dash_reset")])

    await _send_or_edit(update, context, text, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ROUTE_EDITOR_DASHBOARD


async def rental_handle_dashboard_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Диспетчер дій панелі редагування маршруту."""
    query = update.callback_query
    await query.answer()
    data = query.data
    draft = _get_draft(context)

    if data == "rental_dash_add_via":
        return await _render_stop_selection_hub(update, context, step="via")

    if data == "rental_dash_edit_pickup":
        return await _render_stop_selection_hub(update, context, step="pickup")

    if data == "rental_dash_edit_dropoff":
        return await _render_stop_selection_hub(update, context, step="dropoff")

    if data.startswith("rental_dash_del:"):
        idx = int(data.split(":", 1)[1])
        via_pts = draft.get("via_points", [])
        if 0 <= idx < len(via_pts):
            via_pts.pop(idx)
        draft["via_loops"] = [p["stop_name"] for p in via_pts]
        draft["wait_minutes"] = sum(p.get("wait_minutes", 0) for p in via_pts)
        return await _render_route_dashboard(update, context)

    if data == "rental_dash_reset":
        draft["via_loops"] = []
        draft["via_points"] = []
        draft["pickup_stop"] = None
        draft["pickup_direction"] = None
        draft["dropoff_stop"] = None
        draft["wait_minutes"] = 0
        return await _render_stop_selection_hub(update, context, step="pickup")

    return await _render_route_dashboard(update, context)


async def rental_handle_stop_hub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Диспетчер навігації між підрозділами вибору зупинок."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("rental_stop_hub:"):
        step = data.split(":", 1)[1]
        return await _render_stop_selection_hub(update, context, step=step)

    if data.startswith("rental_stop_pop:"):
        _, step, page_str = data.split(":")
        return await _render_popular_stops_picker(update, context, step=step, page=int(page_str))

    if data.startswith("rental_stop_search_prompt:"):
        step = data.split(":", 1)[1]
        return await _render_stop_search_prompt(update, context, step=step)

    if data.startswith("rental_stop_districts:"):
        step = data.split(":", 1)[1]
        return await _render_districts_menu(update, context, step=step)

    if data.startswith("rental_stop_dist:"):
        _, step, d_idx_str = data.split(":")
        return await _render_district_stops(update, context, step=step, district_idx=int(d_idx_str))

    if data.startswith("rental_stop_loops:"):
        _, step, page_str = data.split(":")
        return await _render_loop_picker(update, context, step=step, page=int(page_str))

    if data == "rental_back_pickup":
        return await _render_stop_selection_hub(update, context, step="pickup")

    if data == "rental_back_via":
        return await _render_stop_selection_hub(update, context, step="via")

    return await _render_stop_selection_hub(update, context, step="pickup")


async def _render_loop_picker(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    step: str,
    page: int = 0,
) -> int:
    """
    Відображає пагінований список офіційних розворотних кілець
    для вибору кільця посадки (pickup), проміжних кілець (via) або кільця висадки (dropoff).
    """
    draft = _get_draft(context)
    vt = draft["transport_type"]
    loops = get_available_turning_loops(vt)
    total_pages = max(1, (len(loops) + LOOPS_PAGE_SIZE - 1) // LOOPS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start_idx = page * LOOPS_PAGE_SIZE
    page_loops = loops[start_idx : start_idx + LOOPS_PAGE_SIZE]

    step_labels = {"pickup": "посадки", "via": "проміжного кільця", "dropoff": "висадки"}
    header = (
        f"🔄 <b>РОЗВОРОТНІ КІЛЬЦЯ ОДЕСИ: ТОЧКА {step_labels.get(step, 'посадки').upper()}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>На розворотних кільцях дозволена тривала стоянка вагона (до 10 хв) та безпечний розворот.</i>\n\n"
        f"Сторінка {page + 1}/{total_pages}. Оберіть кільце:"
    )
    prefix = f"rental_loop_{step}"
    if step == "pickup":
        target_state = States.RENTAL_SELECT_PICKUP_LOOP
    elif step == "via":
        target_state = States.RENTAL_SELECT_VIA_LOOPS
    else:
        target_state = States.RENTAL_SELECT_DROPOFF_LOOP

    buttons: List[List[InlineKeyboardButton]] = []
    for idx in range(0, len(page_loops), 2):
        row: List[InlineKeyboardButton] = []
        for j in range(2):
            if idx + j < len(page_loops):
                global_i = start_idx + idx + j
                loop_name = page_loops[idx + j]
                row.append(
                    InlineKeyboardButton(
                        f"🔄 {loop_name}",
                        callback_data=f"{prefix}:{global_i}",
                    )
                )
        buttons.append(row)

    # Навігація сторінками
    nav_row: List[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Попер.", callback_data=f"rental_loop_page:{step}:{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Наст. ➡️", callback_data=f"rental_loop_page:{step}:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    if step == "via":
        buttons.append(
            [InlineKeyboardButton("✅ Перейти до вибору зупинки висадки", callback_data="rental_via_done")]
        )
        if draft.get("via_loops"):
            buttons.append(
                [InlineKeyboardButton("🗑️ Очистити проміжні зупинки", callback_data="rental_via_clear")]
            )

    buttons.append([InlineKeyboardButton("⬅️ До способів вибору", callback_data=f"rental_stop_hub:{step}")])
    await _send_or_edit(update, context, header, InlineKeyboardMarkup(buttons))
    return target_state


async def rental_handle_loop_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, step, page_str = query.data.split(":")
    return await _render_loop_picker(update, context, step=step, page=int(page_str))


async def rental_handle_pickup_loop_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split(":")[1])
    draft = _get_draft(context)
    loops = get_available_turning_loops(draft["transport_type"])
    if 0 <= idx < len(loops):
        draft["pickup_stop"] = loops[idx]
    draft["via_loops"] = []
    return await _render_stop_selection_hub(update, context, step="via")


async def rental_handle_via_loop_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split(":")[1])
    draft = _get_draft(context)
    loops = get_available_turning_loops(draft["transport_type"])
    if 0 <= idx < len(loops):
        chosen = loops[idx]
        context.user_data["rental_pending_via"] = {
            "stop_name": chosen,
            "platform_id": "",
            "direction": "",
        }
        return await _render_via_alighting_prompt(update, context)
    return await _render_stop_selection_hub(update, context, step="via")


async def rental_handle_via_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer("Проміжні зупинки очищено")
    draft = _get_draft(context)
    draft["via_loops"] = []
    draft["via_points"] = []
    draft["wait_minutes"] = 0
    return await _render_stop_selection_hub(update, context, step="via")


async def rental_handle_via_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    return await _render_stop_selection_hub(update, context, step="dropoff")


async def rental_handle_dropoff_loop_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split(":")[1])
    draft = _get_draft(context)
    loops = get_available_turning_loops(draft["transport_type"])
    if 0 <= idx < len(loops):
        draft["dropoff_stop"] = loops[idx]

    if draft["pickup_stop"] == draft["dropoff_stop"] and not draft.get("via_loops"):
        await query.answer(
            "Для кільцевого маршруту (посадка і кінцева на одній зупинці) оберіть хоча б одне проміжне розворотне кільце!",
            show_alert=True,
        )
        return await _render_stop_selection_hub(update, context, step="via")

    return await _render_route_dashboard(update, context)


async def _prompt_wait_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = _get_draft(context)
    via_str = " ➡️ ".join(draft.get("via_loops") or []) or "прямий рейс"
    text = (
        "⏱️ <b>ЧАС ТЕХНОЛОГІЧНОЇ / ЕКСКУРСІЙНОЇ СТОЯНКИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Обраний маршрут:\n<b>{draft['pickup_stop']} ➡️ [{via_str}] ➡️ {draft['dropoff_stop']}</b>\n\n"
        "ℹ️ <i>На зупинці посадки ретро-трамвай прибуває завчасно та очікує замовника в межах технологічного інтервалу лінійних вагонів (до 3–5 хв).</i>\n\n"
        "Оберіть додатковий час стоянки на розворотних кільцях (максимум 10 хвилин, щоб не затримувати лінійний графік):"
    )
    keyboard = [
        [
            InlineKeyboardButton("⏱️ 0 хв", callback_data="rental_wait:0"),
            InlineKeyboardButton("⏱️ 2 хв", callback_data="rental_wait:2"),
            InlineKeyboardButton("⏱️ 5 хв", callback_data="rental_wait:5"),
        ],
        [
            InlineKeyboardButton("⏱️ 7 хв", callback_data="rental_wait:7"),
            InlineKeyboardButton("⏱️ 10 хв", callback_data="rental_wait:10"),
        ],
        [InlineKeyboardButton("⬅️ Змінити маршрут", callback_data="rental_back_rmode")],
    ]
    await _send_or_edit(update, context, text, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_SELECT_WAIT_TIME


async def rental_handle_wait_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    wait_min = int(query.data.split(":")[1])
    draft = _get_draft(context)
    draft["wait_minutes"] = wait_min
    return await _render_route_dashboard(update, context)


# ================= 4. КРОК 3: ВИБІР ДАТИ ТА БАЖАНОГО ЧАСУ ПОДАЧІ =================

async def _render_date_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    draft = _get_draft(context)
    min_date = datetime.date.today() + datetime.timedelta(days=3)

    weekdays_ua = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
    buttons: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for offset in range(12):
        d = min_date + datetime.timedelta(days=offset)
        d_str = d.strftime("%d.%m.%Y")
        wd = weekdays_ua[d.weekday()]
        row.append(
            InlineKeyboardButton(
                f"🗓️ {d.strftime('%d.%m')} ({wd})",
                callback_data=f"rental_date:{d_str}",
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("⬅️ Змінити час стоянки або маршрут", callback_data="rental_back_rmode")])

    text = (
        "📅 <b>КРОК 3 із 6 — ОБЕРІТЬ ДАТУ ПОЇЗДКИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Найближча доступна дата замовлення — <b>{min_date.strftime('%d.%m.%Y')} (+3 дні)</b>.\n\n"
        "• Оберіть бажану дату кнопкою нижче;\n"
        "• Або <b>напишіть дату повідомленням</b> у форматі <code>ДД.ММ.РРРР</code> (наприклад: <code>28.05.2026</code>):"
    )
    if error_msg:
        text = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + text

    await _send_or_edit(update, context, text, InlineKeyboardMarkup(buttons))
    return States.RENTAL_SELECT_DATE


async def rental_handle_date_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    date_str = query.data.split(":", 1)[1]
    draft = _get_draft(context)
    draft["rental_date"] = date_str
    return await _render_slot_selection(update, context)


async def rental_handle_date_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_SELECT_DATE

    raw = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    try:
        parsed_date = datetime.datetime.strptime(raw, "%d.%m.%Y").date()
    except ValueError:
        return await _render_date_selection(
            update,
            context,
            error_msg="Будь ласка, введіть дату у форматі ДД.ММ.РРРР (наприклад, 28.05.2026).",
        )

    min_date = datetime.date.today() + datetime.timedelta(days=3)
    if parsed_date < min_date:
        return await _render_date_selection(
            update,
            context,
            error_msg=f"Мінімальний термін замовлення — не менше ніж за 3 дні (найближча дата: {min_date.strftime('%d.%m.%Y')}).",
        )

    draft = _get_draft(context)
    draft["rental_date"] = parsed_date.strftime("%d.%m.%Y")
    return await _render_slot_selection(update, context)


async def _render_slot_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    draft = _get_draft(context)
    date_str = draft["rental_date"]
    pickup = draft.get("pickup_stop", "пл. Старосінна")

    standard_slots = ["10:00", "11:30", "13:00", "14:30", "16:00", "17:30", "19:00"]
    buttons: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for sl in standard_slots:
        row.append(InlineKeyboardButton(f"🕒 {sl}", callback_data=f"rental_slot:{sl}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("✍️ Вказати свій час", callback_data="rental_slot:CUSTOM")])
    buttons.append([InlineKeyboardButton("⬅️ Обрати іншу дату", callback_data="rental_back_date")])

    text = (
        f"🕒 <b>КРОК 3 із 6 — БАЖАНИЙ ЧАС ПОДАЧІ НА {date_str}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Обране кільце посадки: <b>{pickup}</b>\n\n"
        f"Оберіть бажаний час подачі ретро-вагона зі стандартних вікон або вкажіть власний час:"
    )
    if error_msg:
        text = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + text

    await _send_or_edit(update, context, text, InlineKeyboardMarkup(buttons))
    return States.RENTAL_SELECT_SLOT


async def rental_handle_slot_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    chosen = query.data.split(":", 1)[1]
    draft = _get_draft(context)

    if chosen == "CUSTOM":
        text = (
            "🕒 <b>ВКАЖІТЬ БАЖАНИЙ ЧАС ПОДАЧІ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Введіть бажаний час повідомленням у форматі <code>ГГ:ХХ</code> (наприклад, <code>15:00</code>):"
        )
        keyboard = [[InlineKeyboardButton("⬅️ Назад до вибору слотів", callback_data="rental_back_slot")]]
        await _send_or_edit(update, context, text, InlineKeyboardMarkup(keyboard))
        return States.RENTAL_ENTER_CUSTOM_TIME

    draft["rental_time_slot"] = chosen
    return await _render_wialon_calculation_and_extras(update, context)


async def rental_handle_custom_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_ENTER_CUSTOM_TIME

    raw_t = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    match = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", raw_t)
    if not match:
        return await _render_slot_selection(
            update,
            context,
            error_msg="Будь ласка, введіть коректний час у форматі ГГ:ХХ (наприклад: 15:30).",
        )

    h, m = int(match.group(1)), int(match.group(2))
    formatted_t = f"{h:02d}:{m:02d}"
    draft = _get_draft(context)
    draft["rental_time_slot"] = formatted_t
    return await _render_wialon_calculation_and_extras(update, context)


# ================= 5. КРОК 4: КАЛЬКУЛЯЦІЯ МАРШРУТУ ТА ДОДАТКОВІ ПОСЛУГИ =================

def _compute_draft_wialon_and_price(draft: Dict[str, Any]) -> None:
    via_loops = list(draft.get("via_loops") or [])
    calc_input = RentalCalculationInput(
        transport_type=draft["transport_type"],
        wagon_type=draft["engine_wagon_type"],
        depot_base=draft["depot_code"],
        pickup_stop=draft["pickup_stop"],
        dropoff_stop=draft["dropoff_stop"],
        via_loops=via_loops,
        intermediate_turning_loop=via_loops[0] if via_loops else None,
        wait_minutes_at_loop=int(draft.get("wait_minutes", 0)),
        total_wait_minutes=int(draft.get("wait_minutes", 0)),
        day_type="WEEKEND",
        departure_time=draft.get("rental_time_slot") or "12:00",
    )
    calc_out = calculate_rental_route(calc_input)

    draft["depot_code"] = calc_out.depot_base
    draft["distance_pull_out_km"] = calc_out.phase_1_dispatch.distance_km
    draft["distance_route_km"] = calc_out.phase_2_rental.distance_km
    draft["distance_pull_in_km"] = calc_out.phase_3_return.distance_km
    draft["total_distance_km"] = calc_out.total_billable_km

    draft["duration_pull_out_min"] = calc_out.phase_1_dispatch.motion_minutes
    draft["duration_route_min"] = calc_out.phase_2_rental.motion_minutes
    draft["duration_pull_in_min"] = calc_out.phase_3_return.motion_minutes
    draft["total_duration_min"] = calc_out.total_duration_minutes
    draft["formatted_duration"] = calc_out.formatted_total_duration

    price_bd = calculate_rental_price_breakdown(
        RentalPriceInput(
            wagon_key=draft["wagon_key"],
            total_billable_km=calc_out.total_billable_km,
            total_duration_minutes=calc_out.total_duration_minutes,
            wait_minutes=int(draft.get("wait_minutes", 0)),
            extra_service_keys=list(draft.get("extra_services") or []),
        )
    )
    draft["billable_minutes"] = price_bd.billable_minutes
    draft["time_price_uah"] = price_bd.time_price_uah
    draft["without_vat_uah"] = price_bd.without_vat_uah
    draft["vat_20_uah"] = price_bd.vat_20_uah
    draft["km_price_uah"] = price_bd.time_price_uah
    draft["wait_price_uah"] = 0.0
    draft["extras_price_uah"] = price_bd.extras_price_uah
    draft["total_price_uah"] = price_bd.total_price_uah
    draft["selected_extras_titles"] = price_bd.selected_extras_titles


async def _render_wialon_calculation_and_extras(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    draft = _get_draft(context)
    try:
        _compute_draft_wialon_and_price(draft)
    except Exception as exc:
        logger.error(f"Помилка розрахунку маршруту Wialon: {exc}")
        await _send_or_edit(
            update,
            context,
            f"⚠️ Не вдалося побудувати маршрут між обраними точками: {exc}\nСпробуйте обрати іншу комбінацію кілець.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Обрати інший маршрут", callback_data="rental_back_rmode")]]),
        )
        return States.RENTAL_SELECT_ROUTE_MODE

    via_str = " ➡️ ".join(draft.get("via_loops") or []) or "прямий рейс"
    selected_extras = set(draft.get("extra_services") or [])

    h_part = draft["billable_minutes"] // 60
    m_part = draft["billable_minutes"] % 60
    billable_label = f"{draft['billable_minutes']} хв ({h_part} год {m_part:02d} хв)" if m_part else f"{h_part} год ({draft['billable_minutes']} хв)"
    min_note = " <i>(застосовано мін. замовлення 1 год)</i>" if draft["total_duration_min"] < 60 else ""

    text = (
        "📊 <b>КРОК 4 із 6 — КАЛЬКУЛЯЦІЯ МАРШРУТУ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🚊 <b>Транспорт:</b> {draft['wagon_title']}\n"
        f"📅 <b>Дата та час:</b> <b>{draft['rental_date']}</b> о <b>{draft['rental_time_slot']}</b>\n"
        f"🗺️ <b>Маршрут:</b> {draft['pickup_stop']} ➡️ [{via_str}] ➡️ {draft['dropoff_stop']}\n\n"
        f"📏 <b>Пофазний баланс руху та часу:</b>\n"
        f"1️⃣ <b>Подача з депо:</b> {draft['distance_pull_out_km']:.2f} км ({draft['duration_pull_out_min']} хв)\n"
        f"2️⃣ <b>Орендний маршрут:</b> {draft['distance_route_km']:.2f} км ({draft['duration_route_min']} хв руху + {draft['wait_minutes']} хв стоянки)\n"
        f"3️⃣ <b>Повернення у депо:</b> {draft['distance_pull_in_km']:.2f} км ({draft['duration_pull_in_min']} хв)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ <b>Розрахунковий час оплати:</b> <b>{billable_label}</b>{min_note}\n\n"
        f"💰 <b>Фінансовий розрахунок:</b>\n"
        f"• Оренда вагона РЕТРО: <b>{format_money_ua(draft['time_price_uah'])} грн</b>\n"
        f"• Додаткові послуги: <b>{format_money_ua(draft['extras_price_uah'])} грн</b>\n"
        f"• Сума без ПДВ: <b>{format_money_ua(draft['without_vat_uah'])} грн</b>\n"
        f"• ПДВ, 20%: <b>{format_money_ua(draft['vat_20_uah'])} грн</b>\n"
        f"💳 <b>РАЗОМ ДО СПЛАТИ З ПДВ: {format_money_ua(draft['total_price_uah'])} грн</b>\n\n"
        f"👇 <i>За бажанням додайте сервісні опції та натисніть «Продовжити»:</i>"
    )

    buttons: List[List[InlineKeyboardButton]] = []
    for svc_key, svc_info in RENTAL_EXTRA_SERVICES.items():
        mark = "☑️" if svc_key in selected_extras else "⬜"
        buttons.append(
            [
                InlineKeyboardButton(
                    f"{mark} {svc_info['title']} (+{svc_info['price_uah']:.0f} грн)",
                    callback_data=f"rental_extra:{svc_key}",
                )
            ]
        )

    buttons.append([InlineKeyboardButton("✅ Продовжити -> Вибір формату договору", callback_data="rental_extras_done")])
    buttons.append([InlineKeyboardButton("⬅️ Змінити час або дату", callback_data="rental_back_slot")])
    await _send_or_edit(update, context, text, InlineKeyboardMarkup(buttons))
    return States.RENTAL_SELECT_EXTRAS


async def rental_toggle_extra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    svc_key = query.data.split(":", 1)[1]
    draft = _get_draft(context)
    extras_list: List[str] = list(draft.get("extra_services") or [])
    if svc_key in extras_list:
        extras_list.remove(svc_key)
    else:
        extras_list.append(svc_key)
    draft["extra_services"] = extras_list
    return await _render_wialon_calculation_and_extras(update, context)


# ================= 6. КРОК 5: ВИБІР СЦЕНАРІЮ ПІДПИСАННЯ ДОГОВОРУ =================

async def rental_prompt_signing_scenario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()

    text = (
        "✍️ <b>КРОК 5 із 6 — ОБЕРІТЬ СПОСІБ ПІДПИСАННЯ ДОГОВОРУ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📱 <b>Варіант А — Електронний договір (Дія.Підпис / КЕП .p7s):</b>\n"
        "• Ви підписуєте PDF-договір у додатку «Дія» або онлайн-сервісі «Вчасно» та завантажуєте підписаний файл (<code>.p7s</code> або PDF з КЕП) прямо в бот.\n\n"
        "🏢 <b>Варіант Б — Паперовий договір в Управлінні КП:</b>\n"
        "• Особисте підписання за адресою: <b>м. Одеса, вул. Водопровідна, 1</b> (пн–пт, 09:00–17:00);\n"
        f"• ⏳ На підписання та завантаження скан-копії в розділі «📂 Діючі договори та замовлення» діє ліміт <b>{RENTAL_PAPER_LOCK_HOURS} годин</b>."
    )
    keyboard = [
        [
            InlineKeyboardButton(
                "📱 Електронний договір (Дія.Підпис / КЕП)",
                callback_data="rental_sign:kep",
            )
        ],
        [
            InlineKeyboardButton(
                "🏢 Паперовий договір в Управлінні КП",
                callback_data="rental_sign:paper",
            )
        ],
        [InlineKeyboardButton("⬅️ Назад до калькуляції", callback_data="rental_back_extras")],
    ]
    await _send_or_edit(update, context, text, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_SELECT_SIGNING_SCENARIO


async def rental_handle_signing_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    scenario = query.data.split(":", 1)[1]
    draft = _get_draft(context)
    draft["signing_scenario"] = scenario
    return await _render_safety_briefing(update, context)


# ================= 7. КРОК 6: ПРАВИЛА БЕЗПЕКИ, СТАТУС ТА РЕКВІЗИТИ ЗАМОВНИКА =================

async def _render_safety_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (
        "🛡️ <b>ОБОВ'ЯЗКОВИЙ ІНСТРУКТАЖ ІЗ ПОЖЕЖНОЇ, ЕЛЕКТРО- ТА ТЕХНІЧНОЇ БЕЗПЕКИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Перед формуванням Договору оренди Замовник зобов'язаний ознайомитися та погодитися з правилами безпеки КП «ОМЕТ»:\n\n"
        "1️⃣ <b>Посадка та висадка пасажирів:</b> дозволяються виключно на погоджених розворотних кільцях після повної зупинки вагона та за командою водія.\n"
        "2️⃣ <b>Пожежна та електробезпека:</b> у салоні категорично заборонено куріння (включно з вейпами/електронними сигаретами/IQOS), використання свічок, бенгальських вогнів, хлопавок, піротехніки та будь-якого відкритого вогню.\n"
        "3️⃣ <b>Безпека під час руху:</b> забороняється відволікати водія, заважати керуванню, висовуватися з вікон або дверей, самостійно відчиняти двері під час руху.\n"
        "4️⃣ <b>Санітарний стан та акустика:</b> у салоні заборонено смітити, розпивати міцні спиртні напої. Використання звукопідсилювальної апаратури має бути комфортним і не заважати керуванню вагоном.\n"
        "5️⃣ <b>Місткість:</b> кількість пасажирів у салоні не повинна перевищувати 40 осіб.\n\n"
        "Підтвердіть ознайомлення з правилами безпеки:"
    )
    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Ознайомлений(а) та погоджуюсь",
                callback_data="rental_safety_accept",
            )
        ],
        [InlineKeyboardButton("❌ Відхилити", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, text, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_SAFETY_BRIEFING


async def rental_handle_safety_accepted(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    return await _render_customer_type_selection(update, context)


async def _render_customer_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (
        "👤 <b>КРОК 6 із 6 — СТАТУС ТА РЕКВІЗИТИ ЗАМОВНИКА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Оберіть правовий статус платника для формування офіційного Договору перевезення:\n\n"
        "• <b>Фізична особа</b> — звичайний громадянин (паспорт / ID-картка та РНОКПП);\n"
        "• <b>ФОП</b> — підприємець (Виписка з ЄДР та РНОКПП);\n"
        "• <b>Юридична особа</b> — компанія / організація (ТОВ, ПП, код ЄДРПОУ 8 цифр)."
    )
    keyboard = [
        [InlineKeyboardButton("🚶 Фізична особа (громадянин)", callback_data="rental_cust_type:individual")],
        [InlineKeyboardButton("💼 ФОП (Підприємець)", callback_data="rental_cust_type:fop")],
        [InlineKeyboardButton("🏢 Юридична особа (ТОВ тощо)", callback_data="rental_cust_type:legal_entity")],
        [InlineKeyboardButton("⬅️ Назад до інструктажу", callback_data="rental_back_safety")],
    ]
    await _send_or_edit(update, context, text, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_SELECT_CUSTOMER_TYPE


# ================= ГІЛКА 1: ФІЗИЧНА ОСОБА =================

async def _render_individual_name_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Відображає запит на введення ПІБ фізичної особи."""
    prompt_text = (
        "🚶 <b>ФІЗИЧНА ОСОБА (ГРОМАДЯНИН)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Введіть <b>Ваше ПІБ повністю</b>\n"
        "(наприклад: <code>Перепелиця Олег Олександрович</code>):"
    )
    if error_msg:
        prompt_text = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + prompt_text

    keyboard = [
        [InlineKeyboardButton("⬅️ Змінити статус замовника", callback_data="rental_back_cust_type")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, prompt_text, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ENTER_CUSTOMER_NAME


async def _render_customer_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE, error_msg: Optional[str] = None) -> int:
    return await _render_individual_name_input(update, context, error_msg=error_msg)


async def rental_handle_customer_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        chosen_type = query.data.split(":", 1)[1]
        draft = _get_draft(context)
        draft["customer_type"] = chosen_type

    chosen = draft.get("customer_type", "individual")
    if chosen == "legal_entity":
        return await _render_legal_edrpou_input(update, context)
    if chosen == "fop":
        return await _render_fop_name_input(update, context)
    return await _render_individual_name_input(update, context)


async def _render_individual_phone_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Відображає запит на введення контактного номера телефону громадянина."""
    phone_prompt = "📞 Введіть Ваш <b>контактний номер телефону</b> (наприклад: <code>+380501234567</code>):"
    if error_msg:
        phone_prompt = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + phone_prompt

    keyboard = [
        [InlineKeyboardButton("⬅️ Змінити ПІБ", callback_data="rental_back_name")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, phone_prompt, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ENTER_CUSTOMER_PHONE


async def _render_customer_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE, error_msg: Optional[str] = None) -> int:
    return await _render_individual_phone_input(update, context, error_msg=error_msg)


async def rental_handle_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_ENTER_CUSTOMER_NAME

    name_val = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    if len(name_val) < 3:
        return await _render_individual_name_input(
            update,
            context,
            error_msg="Будь ласка, введіть коректне ПІБ (мінімум 3 символи).",
        )

    draft = _get_draft(context)
    draft["user_full_name"] = name_val
    return await _render_individual_phone_input(update, context)


async def rental_handle_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_ENTER_CUSTOMER_PHONE

    phone_val = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    digits = re.sub(r"\D", "", phone_val)
    if len(digits) < 9:
        return await _render_individual_phone_input(
            update,
            context,
            error_msg="Некоректний номер телефону. Введіть номер у форматі +380XXXXXXXXX.",
        )

    draft = _get_draft(context)
    draft["user_phone"] = phone_val
    return await _render_individual_passport_input(update, context)


async def _render_individual_passport_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Запитує паспорт або ID-картку фізичної особи з можливістю заповнити при підписанні."""
    prompt = (
        "🪪 <b>ПАСПОРТНІ ДАНІ ЗАМОВНИКА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Введіть серію та номер паспорта громадянина України або номер ID-картки\n"
        "(наприклад: <code>паспорт КМ 123456, виданий Приморським РВ</code> або <code>ID-картка №001234567</code>):\n\n"
        "<i>Також Ви можете вказати ці дані безпосередньо при особистому підписанні.</i>"
    )
    if error_msg:
        prompt = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + prompt

    keyboard = [
        [InlineKeyboardButton("⏭️ Вказати під час підписання", callback_data="rental_passp_skip")],
        [InlineKeyboardButton("⬅️ Змінити номер телефону", callback_data="rental_back_phone")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, prompt, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ENTER_INDIVIDUAL_PASSPORT


async def rental_handle_individual_passport_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = _get_draft(context)
    if update.callback_query:
        await update.callback_query.answer()
        draft["user_passport"] = "Вказується при підписанні"
    elif update.message and update.message.text:
        try:
            await update.message.delete()
        except Exception:
            pass
        draft["user_passport"] = update.message.text.strip()

    return await _render_individual_address_input(update, context)


async def _render_individual_address_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Запитує офіційну адресу реєстрації місця проживання фізичної особи (обов'язково)."""
    prompt = (
        "📍 <b>АДРЕСА РЕЄСТРАЦІЇ (ПРОПИСКА)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Введіть офіційну адресу реєстрації місця проживання (згідно паспорта або витягу)\n"
        "(наприклад: <code>65000, м. Одеса, вул. Канатна, 15, кв. 10</code>):"
    )
    if error_msg:
        prompt = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + prompt

    keyboard = [
        [InlineKeyboardButton("⬅️ Змінити паспортні дані", callback_data="rental_back_passport")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, prompt, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ENTER_INDIVIDUAL_ADDRESS


async def rental_handle_individual_address_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_ENTER_INDIVIDUAL_ADDRESS

    addr_val = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    if len(addr_val) < 5:
        return await _render_individual_address_input(
            update,
            context,
            error_msg="Введіть повну адресу (місто, вулиця, будинок). Мінімум 5 символів.",
        )

    draft = _get_draft(context)
    draft["user_address"] = addr_val
    return await _render_individual_tax_input(update, context)


async def _render_individual_tax_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Запитує РНОКПП (ІПН) фізичної особи — обов'язково 10 цифр."""
    prompt = (
        "🪪 <b>РНОКПП (ІПН) ЗАМОВНИКА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Введіть Ваш реєстраційний номер облікової картки платника податків (рівно 10 цифр):"
    )
    if error_msg:
        prompt = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + prompt

    keyboard = [
        [InlineKeyboardButton("⬅️ Змінити адресу реєстрації", callback_data="rental_back_indiv_addr")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, prompt, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ENTER_INDIVIDUAL_TAX_ID


async def _render_customer_tax_input(update: Update, context: ContextTypes.DEFAULT_TYPE, error_msg: Optional[str] = None) -> int:
    return await _render_individual_tax_input(update, context, error_msg=error_msg)


async def rental_handle_individual_tax_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_ENTER_INDIVIDUAL_TAX_ID

    tax_val = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    digits = re.sub(r"\D", "", tax_val)
    if len(digits) != 10:
        return await _render_individual_tax_input(
            update,
            context,
            error_msg="РНОКПП має складатися рівно з 10 цифр. Перевірте та повторіть введення.",
        )

    draft = _get_draft(context)
    draft["user_tax_id"] = digits
    return await _render_final_confirmation(update, context)


async def rental_handle_tax_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await rental_handle_individual_tax_input(update, context)


# ================= ГІЛКА 2: ФОП (ПІДПРИЄМЕЦЬ) =================

async def _render_fop_name_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Запитує ПІБ фізичної особи-підприємця."""
    prompt = (
        "💼 <b>ФОП (ПІДПРИЄМЕЦЬ)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Введіть <b>ПІБ підприємця повністю</b>\n"
        "(наприклад: <code>Коваленко Сергій Васильович</code>):"
    )
    if error_msg:
        prompt = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + prompt

    keyboard = [
        [InlineKeyboardButton("⬅️ Змінити статус замовника", callback_data="rental_back_cust_type")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, prompt, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ENTER_FOP_NAME


async def rental_handle_fop_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_ENTER_FOP_NAME

    name_val = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    if len(name_val) < 3:
        return await _render_fop_name_input(
            update,
            context,
            error_msg="Будь ласка, введіть ПІБ підприємця (мінімум 3 символи).",
        )

    draft = _get_draft(context)
    clean_name = re.sub(r"^(фоп|фізична особа-підприємець)\s+", "", name_val, flags=re.IGNORECASE).strip()
    draft["user_full_name"] = clean_name
    return await _render_fop_tax_input(update, context)


async def _render_fop_tax_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Запитує РНОКПП (ІПН ФОП) — рівно 10 цифр."""
    prompt = (
        "🪪 <b>РНОКПП (ІПН ФОП)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Введіть <b>РНОКПП підприємця (10 цифр)</b> для зазначення в Договорі та Рахунку:"
    )
    if error_msg:
        prompt = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + prompt

    keyboard = [
        [InlineKeyboardButton("⬅️ Змінити ПІБ ФОП", callback_data="rental_back_fop_name")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, prompt, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ENTER_FOP_TAX_ID


async def rental_handle_fop_tax_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_ENTER_FOP_TAX_ID

    tax_val = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    digits = re.sub(r"\D", "", tax_val)
    if len(digits) != 10:
        return await _render_fop_tax_input(
            update,
            context,
            error_msg="РНОКПП ФОП має містити рівно 10 цифр. Повторіть введення.",
        )

    draft = _get_draft(context)
    draft["user_tax_id"] = digits
    return await _render_fop_address_input(update, context)


async def _render_fop_address_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Запитує податкову адресу реєстрації ФОП (обов'язково)."""
    prompt = (
        "📍 <b>ПОДАТКОВА АДРЕСА РЕЄСТРАЦІЇ ФОП</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Введіть офіційну податкову адресу реєстрації підприємця\n"
        "(наприклад: <code>65012, м. Одеса, вул. Рішельєвська, 28, кв. 4</code>):"
    )
    if error_msg:
        prompt = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + prompt

    keyboard = [
        [InlineKeyboardButton("⬅️ Змінити РНОКПП ФОП", callback_data="rental_back_fop_tax")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, prompt, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ENTER_FOP_ADDRESS


async def rental_handle_fop_address_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_ENTER_FOP_ADDRESS

    addr_val = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    if len(addr_val) < 5:
        return await _render_fop_address_input(
            update,
            context,
            error_msg="Введіть повну податкову адресу ФОП (мінімум 5 символів).",
        )

    draft = _get_draft(context)
    draft["user_address"] = addr_val
    return await _render_fop_edr_input(update, context)


async def _render_fop_edr_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Запитує підставу діяльності ФОП (Виписка з ЄДР)."""
    prompt = (
        "📄 <b>ПІДСТАВА ДІЯЛЬНОСТІ ФОП</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Оберіть стандартне формулювання для договору або введіть номер і дату виписки з ЄДР вручну:"
    )
    if error_msg:
        prompt = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + prompt

    keyboard = [
        [InlineKeyboardButton("📄 Згідно Виписки з ЄДР (стандартно)", callback_data="rental_fop_edr_std")],
        [InlineKeyboardButton("⬅️ Змінити податкову адресу", callback_data="rental_back_fop_addr")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, prompt, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ENTER_FOP_EDR_DOC


async def rental_handle_fop_edr_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = _get_draft(context)
    if update.callback_query:
        await update.callback_query.answer()
        draft["foundation_doc"] = "Виписки з Єдиного державного реєстру"
    elif update.message and update.message.text:
        try:
            await update.message.delete()
        except Exception:
            pass
        draft["foundation_doc"] = update.message.text.strip()

    return await _render_fop_phone_input(update, context)


async def _render_fop_phone_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Запитує контактний телефон ФОП."""
    prompt = "📞 Введіть <b>контактний номер телефону підприємця</b> (наприклад: <code>+380671234567</code>):"
    if error_msg:
        prompt = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + prompt

    keyboard = [
        [InlineKeyboardButton("⬅️ Змінити підставу діяльності", callback_data="rental_back_fop_edr")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, prompt, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ENTER_FOP_PHONE


async def rental_handle_fop_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_ENTER_FOP_PHONE

    phone_val = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    digits = re.sub(r"\D", "", phone_val)
    if len(digits) < 9:
        return await _render_fop_phone_input(
            update,
            context,
            error_msg="Некоректний номер телефону. Введіть номер у форматі +380XXXXXXXXX.",
        )

    draft = _get_draft(context)
    draft["user_phone"] = phone_val
    return await _render_final_confirmation(update, context)


# ================= ГІЛКА 3: ЮРИДИЧНА ОСОБА =================

async def _render_legal_edrpou_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Запитує код ЄДРПОУ організації (8 цифр)."""
    prompt = (
        "🏢 <b>ЮРИДИЧНА ОСОБА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Введіть <b>код ЄДРПОУ організації</b> (рівно 8 цифр):"
    )
    if error_msg:
        prompt = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + prompt

    keyboard = [
        [InlineKeyboardButton("⬅️ Змінити статус замовника", callback_data="rental_back_cust_type")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, prompt, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ENTER_LEGAL_EDRPOU


async def rental_handle_legal_edrpou_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_ENTER_LEGAL_EDRPOU

    val = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    digits = re.sub(r"\D", "", val)
    if len(digits) != 8:
        return await _render_legal_edrpou_input(
            update,
            context,
            error_msg="Код ЄДРПОУ має містити рівно 8 цифр. Повторіть введення.",
        )

    draft = _get_draft(context)
    draft["user_tax_id"] = digits
    return await _render_legal_name_input(update, context)


async def _render_legal_name_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Запитує повне найменування юридичної особи."""
    prompt = (
        "🏢 <b>НАЙМЕНУВАННЯ ПІДПРИЄМСТВА / ОРГАНІЗАЦІЇ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Введіть <b>повне найменування юридичної особи</b>\n"
        "(наприклад: <code>ТОВ «Одеський Туристичний Центр»</code>):"
    )
    if error_msg:
        prompt = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + prompt

    keyboard = [
        [InlineKeyboardButton("⬅️ Змінити код ЄДРПОУ", callback_data="rental_back_legal_edrpou")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, prompt, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ENTER_LEGAL_NAME


async def rental_handle_legal_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_ENTER_LEGAL_NAME

    name_val = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    if len(name_val) < 3:
        return await _render_legal_name_input(
            update,
            context,
            error_msg="Найменування компанії має містити щонайменше 3 символи.",
        )

    draft = _get_draft(context)
    draft["user_full_name"] = name_val
    draft["company_name"] = name_val
    return await _render_legal_address_input(update, context)


async def _render_legal_address_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Запитує офіційну юридичну адресу організації за ЄДР."""
    prompt = (
        "📍 <b>ЮРИДИЧНА АДРЕСА ОРГАНІЗАЦІЇ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Введіть офіційну юридичну адресу підприємства за ЄДР\n"
        "(наприклад: <code>вул. Водопровідна, 1, м. Одеса, 65007</code>):"
    )
    if error_msg:
        prompt = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + prompt

    keyboard = [
        [InlineKeyboardButton("⬅️ Змінити назву компанії", callback_data="rental_back_legal_name")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, prompt, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ENTER_LEGAL_ADDRESS


async def rental_handle_legal_address_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_ENTER_LEGAL_ADDRESS

    addr_val = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    if len(addr_val) < 5:
        return await _render_legal_address_input(
            update,
            context,
            error_msg="Введіть повну юридичну адресу підприємства (мінімум 5 символів).",
        )

    draft = _get_draft(context)
    draft["user_address"] = addr_val
    return await _render_legal_signer_input(update, context)


async def _render_legal_signer_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Запитує інформацію про підписанта та документ повноважень юридичної особи."""
    prompt = (
        "✍️ <b>ПІДПИСАНТ ТА ПІДСТАВА ПОВНОВАЖЕНЬ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Введіть посаду та ПІБ підписанта, а також документ-підставу\n"
        "(наприклад: <code>директор Коваленко Іван Іванович, діє на підставі Статуту</code>):"
    )
    if error_msg:
        prompt = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + prompt

    keyboard = [
        [InlineKeyboardButton("📄 За замовчуванням: директор на підставі Статуту", callback_data="rental_legal_signer_std")],
        [InlineKeyboardButton("⬅️ Змінити юридичну адресу", callback_data="rental_back_legal_addr")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, prompt, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ENTER_LEGAL_SIGNER


async def rental_handle_legal_signer_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = _get_draft(context)
    if update.callback_query:
        await update.callback_query.answer()
        draft["signer_title"] = "директора"
        draft["signer_name"] = draft.get("user_full_name", "Керівник")
        draft["foundation_doc"] = "Статуту"
    elif update.message and update.message.text:
        try:
            await update.message.delete()
        except Exception:
            pass
        raw = update.message.text.strip()
        draft["signer_name"] = raw
        draft["signer_title"] = "директора"
        draft["foundation_doc"] = "Статуту"

    return await _render_legal_phone_input(update, context)


async def _render_legal_phone_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_msg: Optional[str] = None,
) -> int:
    """Запитує контактний номер телефону уповноваженої особи / секретаріату юрособи."""
    prompt = "📞 Введіть <b>контактний номер телефону</b> уповноваженої особи (наприклад: <code>+380487175400</code>):"
    if error_msg:
        prompt = f"⚠️ <b>{error_msg}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" + prompt

    keyboard = [
        [InlineKeyboardButton("⬅️ Змінити підписанта", callback_data="rental_back_legal_signer")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, prompt, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_ENTER_LEGAL_PHONE


async def rental_handle_legal_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    if not msg or not msg.text:
        return States.RENTAL_ENTER_LEGAL_PHONE

    phone_val = msg.text.strip()
    try:
        await msg.delete()
    except Exception:
        pass

    digits = re.sub(r"\D", "", phone_val)
    if len(digits) < 7:
        return await _render_legal_phone_input(
            update,
            context,
            error_msg="Некоректний номер телефону. Введіть телефон організації.",
        )

    draft = _get_draft(context)
    draft["user_phone"] = phone_val
    return await _render_final_confirmation(update, context)


async def _render_final_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = _get_draft(context)
    via_str = " ➡️ ".join(draft.get("via_loops") or []) or "прямий рейс"
    scenario_ua = (
        "📱 Електронний договір (Дія.Підпис / КЕП)"
        if draft.get("signing_scenario", "kep") == "kep"
        else f"🏢 Паперовий в Управлінні КП (вул. Водопровідна, 1 — ліміт {RENTAL_PAPER_LOCK_HOURS} год)"
    )

    billable = int(draft.get("billable_minutes") or 60)
    h_part = billable // 60
    m_part = billable % 60
    billable_label = f"{billable} хв ({h_part} год {m_part:02d} хв)" if m_part else f"{h_part} год ({billable} хв)"
    min_note = " (застосовано мін. замовлення 1 год)" if draft.get("total_duration_min", 0) < 60 else ""

    cust_type = draft.get("customer_type", "individual")
    if cust_type == "legal_entity":
        cust_summary = (
            f"🏢 <b>Замовник (Юридична особа):</b> {draft.get('user_full_name', 'Замовник')}\n"
            f"🔢 <b>Код ЄДРПОУ:</b> <code>{draft.get('user_tax_id', '—')}</code> | 📞 <b>Телефон:</b> {draft.get('user_phone', '—')}\n"
            f"📍 <b>Юридична адреса:</b> {draft.get('user_address', '—')}\n"
            f"✍️ <b>Підписант:</b> {draft.get('signer_name', draft.get('user_full_name', 'Керівник'))}\n"
        )
    elif cust_type == "fop":
        cust_summary = (
            f"💼 <b>Замовник (ФОП):</b> {draft.get('user_full_name', 'Підприємець')}\n"
            f"🪪 <b>РНОКПП (ІПН ФОП):</b> <code>{draft.get('user_tax_id', '—')}</code> | 📞 <b>Телефон:</b> {draft.get('user_phone', '—')}\n"
            f"📍 <b>Податкова адреса:</b> {draft.get('user_address', '—')}\n"
            f"📄 <b>Підстава:</b> {draft.get('foundation_doc', 'Виписка з ЄДР')}\n"
        )
    else:
        passp_label = draft.get("user_passport") or "Вказується при підписанні"
        cust_summary = (
            f"👤 <b>Замовник (Фізична особа):</b> {draft.get('user_full_name', 'Громадянин')}\n"
            f"📞 <b>Телефон:</b> {draft.get('user_phone', '—')} | 🪪 <b>РНОКПП:</b> <code>{draft.get('user_tax_id', '—')}</code>\n"
            f"📍 <b>Адреса реєстрації:</b> {draft.get('user_address', '—')}\n"
            f"🪪 <b>Паспорт/ID:</b> {passp_label}\n"
        )

    wagon_label = draft.get("wagon_title") or "Ретро-трамвай МТВ-82"
    r_date = draft.get("rental_date") or "узгоджується"
    r_slot = draft.get("rental_time_slot") or "узгоджується"
    p_stop = draft.get("pickup_stop") or "пл. Старосінна"
    d_stop = draft.get("dropoff_stop") or "пл. Старосінна"
    t_dist = float(draft.get("total_distance_km") or 0.0)
    t_dur = int(draft.get("total_duration_min") or 60)
    t_price = float(draft.get("total_price_uah") or 0.0)
    vat_amt = float(draft.get("vat_20_uah") or (t_price - round(t_price / 1.2, 2)))

    text = (
        "📑 <b>ПЕРЕВІРКА ТА ПІДТВЕРДЖЕННЯ ЗАМОВЛЕННЯ ОРЕНДИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{cust_summary}"
        f"🚊 <b>Транспорт:</b> {wagon_label}\n"
        f"📅 <b>Дата та час:</b> <b>{r_date}</b> о <b>{r_slot}</b>\n"
        f"🗺️ <b>Маршрут:</b> {p_stop} ➡️ [{via_str}] ➡️ {d_stop}\n"
        f"📏 <b>Пофазний баланс:</b> {t_dist:.2f} км | {t_dur} хв "
        f"(до оплати: {billable_label}{min_note})\n"
        f"📝 <b>Формат договору:</b> {scenario_ua}\n"
        f"💳 <b>Загальна сума до оплати:</b> <b>{format_money_ua(t_price)} грн</b> "
        f"(у т.ч. ПДВ 20%: {format_money_ua(vat_amt)} грн)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Після підтвердження бот миттєво згенерує для Вас:\n"
        "1. <b>Договір оренди (PDF)</b>\n"
        "2. <b>Офіційний рахунок-фактуру IBAN (PDF)</b>\n"
        "3. <b>Маршрутний лист Служби руху КП «ОМЕТ» (PDF)</b>."
    )
    keyboard = [
        [InlineKeyboardButton("🚀 Підтвердити та оформити замовлення", callback_data="rental_confirm_create")],
        [InlineKeyboardButton("⬅️ Змінити статус замовника", callback_data="rental_back_cust_type")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="rental_hub")],
    ]
    await _send_or_edit(update, context, text, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_FINAL_CONFIRM


async def rental_finalize_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Створює замовлення в БД, генерує 3 PDF-документи та публікує картку в оперативному штабі."""
    query = update.callback_query
    await query.answer("Формуємо Договір №XXXX-О та IBAN-рахунок...")
    user = update.effective_user
    draft = _get_draft(context)

    order = await db.create_rental_order(
        {
            "user_id": user.id,
            "user_full_name": draft["user_full_name"],
            "user_phone": draft["user_phone"],
            "user_tax_id": draft.get("user_tax_id"),
            "customer_type": draft.get("customer_type", "individual"),
            "company_name": draft.get("company_name"),
            "user_passport": draft.get("user_passport"),
            "user_address": draft.get("user_address"),
            "signer_name": draft.get("signer_name"),
            "foundation_doc": draft.get("foundation_doc"),
            "transport_type": draft["transport_type"],
            "wagon_type": draft["wagon_title"],
            "depot_code": draft["depot_code"],
            "route_mode": draft["route_mode"],
            "preset_name": draft.get("preset_name"),
            "pickup_stop": draft["pickup_stop"],
            "via_loops": draft.get("via_loops", []),
            "dropoff_stop": draft["dropoff_stop"],
            "wait_minutes": draft.get("wait_minutes", 0),
            "extra_services": draft.get("selected_extras_titles", []),
            "distance_pull_out_km": draft["distance_pull_out_km"],
            "distance_route_km": draft["distance_route_km"],
            "distance_pull_in_km": draft["distance_pull_in_km"],
            "total_distance_km": draft["total_distance_km"],
            "duration_pull_out_min": draft["duration_pull_out_min"],
            "duration_route_min": draft["duration_route_min"],
            "duration_pull_in_min": draft["duration_pull_in_min"],
            "total_duration_min": draft["total_duration_min"],
            "km_price_uah": draft["km_price_uah"],
            "wait_price_uah": draft["wait_price_uah"],
            "extras_price_uah": draft["extras_price_uah"],
            "total_price_uah": draft["total_price_uah"],
            "signing_scenario": draft["signing_scenario"],
            "rental_date": draft["rental_date"],
            "rental_time_slot": draft.get("rental_time_slot"),
            "safety_accepted": True,
        }
    )

    # Генеруємо та надсилаємо повний пакет документів (DOCX + PDF) та реквізити IBAN
    await _send_order_pdf_package(context, user.id, order)

    # Публікуємо живу картку в штабному чаті 6 підрозділів
    await post_or_update_staff_order_card(context, order.id)

    deadline_str = (
        order.slot_lock_expires_at.strftime("%d.%m.%Y %H:%M")
        if order.slot_lock_expires_at
        else "протягом 36 годин"
    )
    if order.signing_scenario == "paper":
        next_step_hint = (
            f"🏢 <b>Паперовий договір:</b> роздрукуйте або підпишіть примірник в Управлінні КП «ОМЕТ» "
            f"(<b>вул. Водопровідна, 1</b>, 09:00–17:00) та завантажте скан-копію в розділі "
            f"<b>«📂 Діючі договори та замовлення»</b> до <b>{deadline_str}</b> (протягом 36 годин)."
        )
    else:
        next_step_hint = (
            "📱 <b>Електронний договір (КЕП / Дія.Підпис):</b> підпишіть отриманий файл Договору "
            "у «Дії» або «Вчасно» та завантажте підписаний файл (<code>.p7s</code> або PDF з КЕП) "
            "у розділі <b>«📂 Діючі договори та замовлення»</b>."
        )

    summary_text = (
        f"✅ <b>ЗАМОВЛЕННЯ УСПІШНО ОФОРМЛЕНО! ДОГОВІР № {order.contract_number}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Вище Вам надіслано офіційні документи (PDF):\n"
        f"1️⃣ Договір оренди № {order.contract_number} (PDF);\n"
        f"2️⃣ Рахунок IBAN із QR-кодом НБУ на суму <b>{format_money_ua(order.total_price_uah)} грн</b>;\n"
        f"3️⃣ Маршрутний лист Служби руху Wialon (PDF).\n\n"
        f"{next_step_hint}"
    )
    keyboard = [
        [
            InlineKeyboardButton(
                f"📤 Завантажити підписаний договір №{order.contract_number}",
                callback_data=f"rental_upload_signed:{order.id}",
            )
        ],
        [
            InlineKeyboardButton(
                f"💳 Завантажити квитанцію оплати IBAN",
                callback_data=f"rental_upload_payment:{order.id}",
            )
        ],
        [
            InlineKeyboardButton(
                "📥 Отримати мої документи повторно (PDF)",
                callback_data=f"rental_resend_docs:{order.id}",
            )
        ],
        [InlineKeyboardButton("📂 Діючі договори та замовлення", callback_data="rental_my_contracts")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")],
    ]
    await _send_or_edit(update, context, summary_text, InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END


async def _send_order_pdf_package(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    order: RentalOrder,
) -> None:
    """Генерує та надсилає клієнту 4 файли (Договір DOCX та PDF, Рахунок IBAN з QR НБУ, Маршрутний лист) та реквізити для швидкого копіювання."""
    via_loops: List[str] = []
    try:
        via_loops = json.loads(order.via_loops_json or "[]")
    except Exception:
        via_loops = []

    order_dict = {
        "contract_number": order.contract_number,
        "contract_date": order.created_at.strftime("%d.%m.%Y") if order.created_at else datetime.datetime.now().strftime("%d.%m.%Y"),
        "order_uid": order.order_uid,
        "user_full_name": order.user_full_name,
        "user_phone": order.user_phone,
        "user_tax_id": order.user_tax_id,
        "user_email": order.user_email,
        "customer_type": getattr(order, "customer_type", "individual"),
        "company_name": getattr(order, "company_name", None),
        "user_passport": getattr(order, "user_passport", None),
        "user_address": getattr(order, "user_address", None),
        "signer_name": getattr(order, "signer_name", None),
        "foundation_doc": getattr(order, "foundation_doc", None),
        "transport_type": order.transport_type,
        "wagon_type": order.wagon_type,
        "depot_code": order.depot_code,
        "pickup_stop": order.pickup_stop,
        "via_loops": via_loops,
        "dropoff_stop": order.dropoff_stop,
        "wait_minutes": order.wait_minutes,
        "distance_pull_out_km": order.distance_pull_out_km,
        "distance_route_km": order.distance_route_km,
        "distance_pull_in_km": order.distance_pull_in_km,
        "total_distance_km": order.total_distance_km,
        "duration_pull_out_min": order.duration_pull_out_min,
        "duration_route_min": order.duration_route_min,
        "duration_pull_in_min": order.duration_pull_in_min,
        "total_duration_min": order.total_duration_min,
        "km_price_uah": order.km_price_uah,
        "wait_price_uah": order.wait_price_uah,
        "extras_price_uah": order.extras_price_uah,
        "total_price_uah": order.total_price_uah,
        "signing_scenario": order.signing_scenario,
        "rental_date": order.rental_date,
        "rental_time_slot": order.rental_time_slot,
    }

    try:
        contract_docx = generate_rental_contract_docx(order_dict)
        contract_pdf = generate_rental_contract_pdf(order_dict)
        invoice_pdf = generate_rental_iban_invoice_pdf(order_dict)

        engine_w_type = "retro" if ("Ретро" in order.wagon_type or "МТВ" in order.wagon_type or "914" in order.wagon_type) else "standard"
        calc_out = calculate_rental_route(
            RentalCalculationInput(
                order_id=order.contract_number,
                transport_type=order.transport_type,
                wagon_type=engine_w_type,
                depot_base=order.depot_code,
                pickup_stop=order.pickup_stop,
                dropoff_stop=order.dropoff_stop,
                via_loops=via_loops,
                intermediate_turning_loop=via_loops[0] if via_loops else None,
                wait_minutes_at_loop=order.wait_minutes,
                total_wait_minutes=order.wait_minutes,
                departure_time=order.rental_time_slot or "12:00",
            )
        )
        route_pdf = generate_rental_route_sheet_pdf(calc_out, wagon_title=order.wagon_type)

        del_file_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🗑️ Видалити цей файл", callback_data="rental_del_file")]]
        )

        for path_str, caption_str in [
            (contract_pdf, f"📄 Договір оренди № {order.contract_number} (Adobe PDF)"),
            (invoice_pdf, f"💳 Офіційний рахунок-фактура IBAN (Договір № {order.contract_number})"),
            (route_pdf, f"🗺️ Маршрутний лист Служби руху КП «ОМЕТ» (№ {order.contract_number})"),
        ]:
            if os.path.exists(path_str):
                with open(path_str, "rb") as f_doc:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=f_doc,
                        filename=os.path.basename(path_str),
                        caption=caption_str,
                        reply_markup=del_file_kb,
                    )

        # Повідомлення для швидкої оплати (копіювання реквізитів в 1 клік)
        contract_d = order.created_at.strftime("%d.%m.%Y") if order.created_at else datetime.datetime.now().strftime("%d.%m.%Y")
        purpose = build_nbu_iban_payment_purpose(order.contract_number, contract_d)
        vat_val = order.total_price_uah / 6.0

        copy_text = (
            "💳 <b>РЕКВІЗИТИ ДЛЯ ОПЛАТИ IBAN (натисніть на поле для копіювання):</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Отримувач:</b>\n<code>{RENTAL_IBAN_COMPANY_NAME}</code>\n\n"
            f"• <b>Код ЄДРПОУ:</b>\n<code>{RENTAL_IBAN_EDRPOU}</code>\n\n"
            f"• <b>Рахунок IBAN:</b>\n<code>{RENTAL_IBAN_ACCOUNT}</code>\n\n"
            f"• <b>Сума до сплати (з ПДВ 20%):</b>\n<code>{order.total_price_uah:.2f}</code> грн "
            f"<i>(у т.ч. ПДВ 20%: {vat_val:.2f} грн)</i>\n\n"
            f"• <b>Призначення платежу:</b>\n<code>{purpose}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📱 <i>Порада: скопіюйте IBAN та призначення платежу одним дотиком для швидкої оплати у додатку Вашого банку.</i>"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=copy_text,
            parse_mode=ParseMode.HTML,
        )

    except Exception as exc:
        logger.error(f"Помилка генерації/відправки пакета документів для замовлення #{order.id}: {exc}")


async def rental_handle_delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Видаляє повідомлення з прикріпленим документом за запитом користувача."""
    query = update.callback_query
    if not query:
        return
    try:
        await query.answer("Файл видалено з чату.")
        if query.message:
            await query.message.delete()
    except Exception as exc:
        logger.warning(f"Не вдалося видалити повідомлення з файлом: {exc}")


async def rental_handle_resend_docs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Повторно надсилає клієнту повний пакет документів та реквізити замовлення."""
    query = update.callback_query
    if not query:
        return
    await query.answer("Надсилаємо документи...")
    try:
        order_id = int(query.data.split(":")[1])
    except Exception:
        return
    order = await db.get_rental_order(order_id)
    if not order or order.user_id != update.effective_user.id:
        await query.answer("Замовлення не знайдено.", show_alert=True)
        return
    await _send_order_pdf_package(context, update.effective_chat.id, order)


# ================= 8. КАБІНЕТ КЛІЄНТА: «📂 ДІЮЧІ ДОГОВОРИ ТА ЗАМОВЛЕННЯ» =================

async def show_my_rental_contracts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Відображає список діючих договорів та замовлень клієнта."""
    query = update.callback_query
    if query:
        await query.answer()
    user = update.effective_user
    if not user or not is_rental_access_allowed(user.id):
        return

    orders = await db.get_user_active_rental_orders(user.id)
    if not orders:
        text = (
            "📂 <b>ДІЮЧІ ДОГОВОРИ ТА ЗАМОВЛЕННЯ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "У Вас наразі немає активних договорів оренди.\n"
            "Натисніть кнопку нижче, щоб розрахувати маршрут та оформити замовлення:"
        )
        keyboard = [
            [InlineKeyboardButton("🚋 Оформити нове замовлення", callback_data="rental_start_wizard")],
            [InlineKeyboardButton("⬅️ Назад у меню оренди", callback_data="rental_hub")],
        ]
        await _send_or_edit(update, context, text, InlineKeyboardMarkup(keyboard))
        return

    text = (
        "📂 <b>ВАШІ ДІЮЧІ ДОГОВОРИ ТА ЗАМОВЛЕННЯ ОРЕНДИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Оберіть договір зі списку нижче, щоб завантажити PDF-документи, обрати час подачі "
        "або прикріпити підписаний договір (.p7s / скан) та квитанцію IBAN:\n\n"
    )
    buttons: List[List[InlineKeyboardButton]] = []
    now_dt = datetime.datetime.now()
    for o in orders:
        timer_str = ""
        if o.status == "awaiting_signature" and o.slot_lock_expires_at:
            rem_sec = (o.slot_lock_expires_at - now_dt).total_seconds()
            if rem_sec > 0:
                rem_h = int(rem_sec // 3600)
                rem_m = int((rem_sec % 3600) // 60)
                timer_str = f" | ⏳ залишилось {rem_h} год {rem_m} хв"
        text += (
            f"• <b>Договір № {o.contract_number}</b> ({o.wagon_type})\n"
            f"  📅 {o.rental_date} ({o.rental_time_slot or 'очікує слоту'}) | 💰 {o.total_price_uah:.2f} грн\n"
            f"  Статус: {STATUS_LABELS_UA.get(o.status, o.status)}{timer_str}\n\n"
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    f"📄 Договір № {o.contract_number} ({o.rental_date})",
                    callback_data=f"rental_contract_view:{o.id}",
                )
            ]
        )

    buttons.append([InlineKeyboardButton("➕ Оформити ще одне замовлення", callback_data="rental_start_wizard")])
    buttons.append([InlineKeyboardButton("⬅️ Назад у меню оренди", callback_data="rental_hub")])
    await _send_or_edit(update, context, text, InlineKeyboardMarkup(buttons))


async def show_rental_contract_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Детальна картка конкретного договору в кабінеті клієнта."""
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split(":")[1])
    order = await db.get_rental_order(order_id)
    if not order or order.user_id != update.effective_user.id:
        await query.answer("Договір не знайдено.", show_alert=True)
        return

    via_loops: List[str] = []
    try:
        via_loops = json.loads(order.via_loops_json or "[]")
    except Exception:
        via_loops = []
    via_str = " ➡️ ".join(via_loops) if via_loops else "прямий рейс"

    purpose = build_nbu_iban_payment_purpose(
        order.contract_number,
        order.created_at.strftime("%d.%m.%Y") if order.created_at else datetime.datetime.now().strftime("%d.%m.%Y"),
    )

    deadline_info = ""
    if order.status == "awaiting_signature" and order.slot_lock_expires_at:
        deadline_info = (
            f"\n⏳ <b>Ліміт часу на завантаження підписаного договору (36 год):</b> "
            f"до <b>{order.slot_lock_expires_at.strftime('%d.%m.%Y %H:%M')}</b>\n"
        )

    vehicle_info = ""
    if order.assigned_board_number:
        vehicle_info = (
            f"\n🚋 <b>Призначений борт:</b> № {order.assigned_board_number} | "
            f"Водій: {order.assigned_driver_name or '—'} ({order.assigned_driver_phone or '—'})\n"
        )

    text = (
        f"📄 <b>ДОГОВІР ОРЕНДИ № {order.contract_number}</b>\n"
        f"Статус: <b>{STATUS_LABELS_UA.get(order.status, order.status)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🚊 <b>Транспорт:</b> {order.wagon_type} (Депо: {order.depot_code})\n"
        f"📅 <b>Дата та час подачі:</b> {order.rental_date} о <b>{order.rental_time_slot or 'очікує вибору слоту'}</b>\n"
        f"🗺️ <b>Маршрут:</b> {order.pickup_stop} ➡️ [{via_str}] ➡️ {order.dropoff_stop}\n"
        f"📏 <b>Кілометраж Wialon:</b> {order.total_distance_km:.2f} км ({order.total_duration_min} хв)"
        f"{deadline_info}{vehicle_info}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 <b>РЕКВІЗИТИ ОПЛАТИ IBAN (З ПДВ 20%):</b>\n"
        f"• Отримувач: <code>{RENTAL_IBAN_COMPANY_NAME}</code>\n"
        f"• ЄДРПОУ: <code>{RENTAL_IBAN_EDRPOU}</code>\n"
        f"• Рахунок IBAN: <code>{RENTAL_IBAN_ACCOUNT}</code>\n"
        f"• Сума до сплати: <b>{order.total_price_uah:.2f} грн</b> (у т.ч. ПДВ 20%: {order.total_price_uah / 6.0:.2f} грн)\n"
        f"• Призначення платежу:\n<code>{purpose}</code>"
    )

    buttons: List[List[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                "📤 Завантажити підписаний договір (.p7s / скан)",
                callback_data=f"rental_upload_signed:{order.id}",
            )
        ],
        [
            InlineKeyboardButton(
                "💳 Завантажити квитанцію оплати IBAN",
                callback_data=f"rental_upload_payment:{order.id}",
            )
        ],
        [
            InlineKeyboardButton(
                "📥 Отримати мої документи повторно (PDF)",
                callback_data=f"rental_resend_docs:{order.id}",
            )
        ],
        [InlineKeyboardButton("⬅️ До списку договорів", callback_data="rental_my_contracts")],
    ]
    await _send_or_edit(update, context, text, InlineKeyboardMarkup(buttons))


async def handle_rental_redownload_pdfs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await rental_handle_resend_docs(update, context)


async def handle_client_pick_order_slot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Коли Служба руху додає вільні слоти у пул на дату, клієнт натискає кнопку
    `rental_pick_order_slot:<order_id>:<slot_time>`.
    Обраний слот бронюється за цим замовленням, а інші слоти залишаються вільними!
    """
    query = update.callback_query
    parts = query.data.split(":", 2)
    order_id = int(parts[1])
    slot_time = parts[2]

    order = await db.get_rental_order(order_id)
    if not order or order.user_id != update.effective_user.id:
        await query.answer("Замовлення не знайдено.", show_alert=True)
        return

    locked_ok = await db.lock_rental_slot(
        rental_date=order.rental_date,
        slot_time=slot_time,
        transport_type=order.transport_type,
        order_id=order.id,
    )
    if not locked_ok:
        free_left = await db.get_available_rental_slots(order.rental_date, order.transport_type)
        await query.answer(
            "⚠️ Цей слот щойно забронював інший замовник! Оберіть інший вільний час зі списку.",
            show_alert=True,
        )
        if free_left:
            kb = [
                [InlineKeyboardButton(f"🕒 Обрати {sl}", callback_data=f"rental_pick_order_slot:{order.id}:{sl}")]
                for sl in free_left
            ]
            await _send_or_edit(
                update,
                context,
                f"Оберіть доступний слот на <b>{order.rental_date}</b>:",
                InlineKeyboardMarkup(kb),
            )
        return

    lock_hours = RENTAL_PAPER_LOCK_HOURS if order.signing_scenario == "paper" else 24
    expires_at = datetime.datetime.now() + datetime.timedelta(hours=lock_hours)
    updated = await db.update_rental_order_fields(
        order.id,
        {
            "rental_time_slot": slot_time,
            "slot_lock_expires_at": expires_at,
            "status": "awaiting_signature",
        },
    )
    await db.add_rental_audit_log(
        order_id=order.id,
        actor_id=order.user_id,
        actor_name=order.user_full_name,
        actor_role="Клієнт",
        action="SLOT_LOCKED",
        details=f"Клієнт обрав слот {slot_time} на {order.rental_date} (бронь до {expires_at.strftime('%d.%m %H:%M')})",
    )
    await post_or_update_staff_order_card(context, order.id)
    await query.answer(f"✅ Слот {slot_time} успішно заброньовано!")

    if updated:
        await _send_order_pdf_package(context, order.user_id, updated)
        await _send_or_edit(
            update,
            context,
            f"✅ <b>Часовий слот {slot_time} на {order.rental_date} закріплено за Договором № {order.contract_number}!</b>\n"
            f"Оновлений пакет документів (Договір + Рахунок IBAN з QR-кодом) надіслано вище.",
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📤 Завантажити підписаний договір (.p7s / скан)",
                            callback_data=f"rental_upload_signed:{order.id}",
                        )
                    ],
                    [InlineKeyboardButton("📂 Мої діючі договори", callback_data="rental_my_contracts")],
                ]
            ),
        )


# ================= 9. ЗАВАНТАЖЕННЯ ПІДПИСАНОГО ДОГОВОРУ (.P7S / СКАН) ТА КВИТАНЦІЇ IBAN =================

async def rental_start_upload_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Переводить клієнта в режим завантаження підписаного договору або квитанції IBAN."""
    query = update.callback_query
    await query.answer()
    action, order_id_str = query.data.split(":", 1)
    order_id = int(order_id_str)
    order = await db.get_rental_order(order_id)
    if not order or order.user_id != update.effective_user.id:
        await query.answer("Договір не знайдено.", show_alert=True)
        return ConversationHandler.END

    upload_kind = "signed_contract" if action == "rental_upload_signed" else "payment_receipt"
    context.user_data["rental_upload_target"] = {
        "order_id": order.id,
        "kind": upload_kind,
    }

    if upload_kind == "signed_contract":
        prompt_text = (
            f"📤 <b>ЗАВАНТАЖЕННЯ ПІДПИСАНОГО ДОГОВОРУ № {order.contract_number}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Надішліть у відповідь файл або фото:\n"
            f"• Для електронного підпису (Дія.Підпис / Вчасно): файл із розширенням <code>.p7s</code> або підписаний <code>.pdf</code>;\n"
            f"• Для паперового договору (підписаного в Управлінні КП на вул. Водопровідна, 1): скан-копію або чітке фото підписаного примірника."
        )
    else:
        prompt_text = (
            f"💳 <b>ЗАВАНТАЖЕННЯ КВИТАНЦІЇ ОПЛАТИ IBAN ЗА ДОГОВОРОМ № {order.contract_number}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Надішліть у відповідь PDF-квитанцію або скріншот оплати з Приват24 / Monobank на суму <b>{order.total_price_uah:.2f} грн</b>."
        )

    keyboard = [[InlineKeyboardButton("⬅️ Скасувати завантаження", callback_data=f"rental_contract_view:{order.id}")]]
    await _send_or_edit(update, context, prompt_text, InlineKeyboardMarkup(keyboard))
    return States.RENTAL_UPLOAD_SIGNED_DOC


async def rental_receive_uploaded_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Приймає файл або фото від клієнта, пересилає в штабний чат, на email Юрвідділу та оновлює статус."""
    msg = update.message
    target = context.user_data.get("rental_upload_target")
    if not msg or not target:
        return ConversationHandler.END

    order_id = int(target["order_id"])
    kind = target["kind"]
    order = await db.get_rental_order(order_id)
    if not order:
        try:
            await msg.delete()
        except Exception:
            pass
        await _send_or_edit(
            update,
            context,
            "❌ Замовлення не знайдено.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🚋 На головну оренди", callback_data="rental_hub")]]),
        )
        return ConversationHandler.END

    file_id: Optional[str] = None
    file_name: str = f"Contract_{order.contract_number}.pdf"
    is_photo = False

    if msg.document:
        file_id = msg.document.file_id
        file_name = msg.document.file_name or file_name
    elif msg.photo:
        file_id = msg.photo[-1].file_id
        file_name = f"Scan_{order.contract_number}.jpg"
        is_photo = True
    else:
        try:
            await msg.delete()
        except Exception:
            pass
        prompt_text = (
            "⚠️ <b>Будь ласка, надішліть документ (файл .p7s / .pdf) або фотографію.</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        if kind == "signed_contract":
            prompt_text += (
                f"✍️ <b>ЗАВАНТАЖЕННЯ ПІДПИСАНОГО ДОГОВОРУ № {order.contract_number}</b>\n\n"
                "Будь ласка, надішліть сюди у відповідь підписаний файл договору:\n"
                "• <b>Електронний підпис:</b> файл із розширенням <code>.p7s</code> (Дія.Підпис / КЕП)\n"
                "• <b>Паперовий примірник:</b> скан-копію або якісне фото кожної сторінки (.pdf / .jpg)."
            )
        else:
            prompt_text += (
                f"💳 <b>ЗАВАНТАЖЕННЯ КВИТАНЦІЇ ОПЛАТИ IBAN (Договір № {order.contract_number})</b>\n\n"
                f"Будь ласка, надішліть файл квитанції або фото чека про переказ коштів на суму "
                f"<b>{order.total_price_uah:.2f} грн</b> за офіційними реквізитами КП «ОМЕТ»."
            )
        keyboard = [[InlineKeyboardButton("⬅️ Скасувати завантаження", callback_data=f"rental_contract_view:{order.id}")]]
        await _send_or_edit(update, context, prompt_text, InlineKeyboardMarkup(keyboard))
        return States.RENTAL_UPLOAD_SIGNED_DOC

    # Видаляємо повідомлення користувача з надісланим документом для чистоти чату
    try:
        await msg.delete()
    except Exception:
        pass

    staff_chat_id = order.staff_chat_id or get_active_staff_chat_id()

    if kind == "signed_contract":
        new_status = "signed_uploaded" if order.status in ("awaiting_signature", "pending_slots", "awaiting_slot_choice") else order.status
        await db.update_rental_order_fields(
            order.id,
            {
                "signed_file_id": file_id,
                "signed_file_name": file_name,
                "status": new_status,
            },
        )
        await db.add_rental_audit_log(
            order_id=order.id,
            actor_id=order.user_id,
            actor_name=order.user_full_name,
            actor_role="Клієнт",
            action="SIGNED_DOC_UPLOADED",
            details=f"Завантажено підписаний договір: {file_name}",
        )

        # Завантажуємо файл у тимчасову папку для відправки на email Юридичного відділу
        try:
            tg_file = await context.bot.get_file(file_id)
            tmp_dir = Path(tempfile.gettempdir()) / "transport_bot_rentals"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            local_path = str(tmp_dir / f"signed_{order.id}_{file_name}")
            await tg_file.download_to_drive(custom_path=local_path)
            asyncio.get_running_loop().run_in_executor(
                None,
                send_legal_contract_email,
                local_path,
                order.contract_number,
                order.user_full_name,
                order.signing_scenario,
            )
        except Exception as email_err:
            logger.warning(f"Не вдалося надіслати файл договору на email Юрвідділу: {email_err}")

        # Дублюємо файл у профільну тему Юридичного відділу
        caption_staff = (
            f"✍️ <b>ОТРИМАНО ПІДПИСАНИЙ ДОГОВІР № {order.contract_number}</b>\n"
            f"👤 Замовник: {order.user_full_name} ({order.user_phone})\n"
            f"📎 Файл: <code>{file_name}</code>\n"
            f"⚖️ Для погодження натисніть <b>«⚖️ Договір перевірено та погоджено»</b> на картці замовлення."
        )
        legal_thread_id = get_staff_topic_thread_id("legal")
        send_doc_kwargs: Dict[str, Any] = {
            "chat_id": staff_chat_id,
            "caption": caption_staff,
            "parse_mode": ParseMode.HTML,
        }
        if legal_thread_id is not None:
            send_doc_kwargs["message_thread_id"] = legal_thread_id
        try:
            if is_photo:
                await context.bot.send_photo(photo=file_id, **send_doc_kwargs)
            else:
                await context.bot.send_document(document=file_id, **send_doc_kwargs)
        except Exception as st_err:
            logger.warning(f"Не вдалося переслати підписаний договір у штабний чат: {st_err}")

        await post_or_update_staff_order_card(context, order.id)
        del context.user_data["rental_upload_target"]

        confirm_text = (
            f"✅ <b>Підписаний договір № {order.contract_number} ({file_name}) успішно отримано!</b>\n\n"
            f"Документ передано до Відділу правового супроводу КП «ОМЕТ» та зафіксовано в системі."
        )
        confirm_kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "💳 Завантажити квитанцію оплати IBAN",
                        callback_data=f"rental_upload_payment:{order.id}",
                    )
                ],
                [InlineKeyboardButton("📂 Мої діючі договори", callback_data="rental_my_contracts")],
            ]
        )
        await _send_or_edit(update, context, confirm_text, confirm_kb)
        return ConversationHandler.END

    # kind == "payment_receipt"
    await db.update_rental_order_fields(order.id, {"payment_file_id": file_id})
    await db.add_rental_audit_log(
        order_id=order.id,
        actor_id=order.user_id,
        actor_name=order.user_full_name,
        actor_role="Клієнт",
        action="PAYMENT_RECEIPT_UPLOADED",
        details=f"Завантажено квитанцію оплати IBAN ({file_name}) на суму {order.total_price_uah:.2f} грн",
    )

    caption_acc = (
        f"💳 <b>ОТРИМАНО КВИТАНЦІЮ ОПЛАТИ IBAN ЗА ДОГОВОРОМ № {order.contract_number}</b>\n"
        f"👤 Замовник: {order.user_full_name} ({order.user_phone})\n"
        f"💰 Сума за договором: <b>{order.total_price_uah:.2f} грн</b>\n"
        f"Для підтвердження зарахування коштів натисніть <b>«💳 Оплату IBAN зараховано (100%)»</b> на картці замовлення."
    )
    acc_thread_id = get_staff_topic_thread_id("accounting")
    send_acc_kwargs: Dict[str, Any] = {
        "chat_id": staff_chat_id,
        "caption": caption_acc,
        "parse_mode": ParseMode.HTML,
    }
    if acc_thread_id is not None:
        send_acc_kwargs["message_thread_id"] = acc_thread_id
    try:
        if is_photo:
            await context.bot.send_photo(photo=file_id, **send_acc_kwargs)
        else:
            await context.bot.send_document(document=file_id, **send_acc_kwargs)
    except Exception as st_err:
        logger.warning(f"Не вдалося переслати квитанцію у штабний чат: {st_err}")

    await post_or_update_staff_order_card(context, order.id)
    del context.user_data["rental_upload_target"]

    receipt_text = (
        f"✅ <b>Квитанцію оплати IBAN за Договором № {order.contract_number} успішно отримано!</b>\n\n"
        f"Документ передано до Бухгалтерії КП «ОМЕТ». Після підтвердження оплати та призначення вагона в депо "
        f"Ви отримаєте електронний посадковий талон із QR-кодом."
    )
    receipt_kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📂 Мої діючі договори", callback_data="rental_my_contracts")]]
    )
    await _send_or_edit(update, context, receipt_text, receipt_kb)
    return ConversationHandler.END
