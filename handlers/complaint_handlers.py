import logging
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode
from services.tickets_service import TicketsService
from config.messages import MESSAGES
from config.settings import ROUTES
from utils.logger import logger
from bot.states import States
from handlers.common import get_cancel_keyboard


# Скомпілюємо список всіх валідних маршрутів
ALL_ROUTES = set(str(r) for r in ROUTES["tram"] + ROUTES["trolleybus"])
# ===== СКАРГИ =====

async def complaint_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок скарги"""
    logger.info(f"User {update.effective_user.id} started complaint")
    keyboard = await get_cancel_keyboard("feedback_menu") # <-- Додаємо клавіатуру
    await update.callback_query.edit_message_text(
        text=MESSAGES['complaint_start'],
        reply_markup=keyboard # <-- Додаємо клавіатуру
    )
    return States.COMPLAINT_PROBLEM


async def complaint_get_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання проблеми та запит маршруту."""
    context.user_data['complaint_problem'] = update.message.text
    logger.info(f"Problem: {update.message.text[:50]}")

    keyboard = await get_cancel_keyboard("feedback_menu")
    await update.message.reply_text(
        MESSAGES['complaint_route'],
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    return States.COMPLAINT_ROUTE


async def complaint_get_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ маршруту."""
    route_text = update.message.text.strip()
    keyboard = await get_cancel_keyboard("feedback_menu")

    # ВАЛІДАЦІЯ:
    if route_text not in ALL_ROUTES:
        await update.message.reply_text(
            f"❌ Маршруту '<b>{route_text}</b>' не знайдено.\n\n"
            f"Будь ласка, введіть коректний номер трамваю або тролейбусу (тільки цифри).",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        return States.COMPLAINT_ROUTE # Повертаємо на той самий крок

    # Валідація пройдена:
    context.user_data['complaint_route'] = route_text
    logger.info(f"Route: {route_text}")

    await update.message.reply_text(
        MESSAGES['complaint_board'],
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    return States.COMPLAINT_BOARD

async def complaint_get_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ бортового номера."""
    board_text = update.message.text.strip()
    keyboard = await get_cancel_keyboard("feedback_menu")

    # ВАЛІДАЦІЯ: 4 цифри
    if not re.match(r"^\d{4}$", board_text):
        await update.message.reply_text(
            f"❌ Невірний формат бортового номера.\n\n"
            f"Це має бути <b>4-значне число</b> (наприклад: <code>4015</code>). Спробуйте ще раз.",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        return States.COMPLAINT_BOARD # Повертаємо на той самий крок

    # Валідація пройдена:
    context.user_data['complaint_board'] = board_text
    logger.info(f"Board: {board_text}")

    await update.message.reply_text(
        MESSAGES['complaint_datetime'],
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    return States.COMPLAINT_DATETIME


async def complaint_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ дати/часу."""
    datetime_text = update.message.text.strip()
    keyboard = await get_cancel_keyboard("feedback_menu")

    # ВАЛІДАЦІЯ:
    try:
        # --- ПОЧАТОК НОВОЇ ВАЛІДАЦІЇ ---

        # 1. Перевірка формату (як і раніше)
        if not re.match(r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$", datetime_text):
            raise ValueError("Невірний формат. Очікується <code>ДД.ММ.РРРР ГГ:ХХ</code>.")

        # 2. Перевірка коректності дати (напр., не 30.02 або 13-й місяць)
        try:
            parsed_date = datetime.strptime(datetime_text, '%d.%m.%Y %H:%M')
        except ValueError:
            raise ValueError("Некоректна дата. Можливо, неіснуючий день або місяць?")

        # Отримуємо поточний час
        now = datetime.now()

        # 3. Перевірка "майбутнього" (як і раніше)
        if parsed_date > now:
            raise ValueError("Дата інциденту не може бути у майбутньому.")

        # 4. НОВА ПЕРЕВІРКА: Тільки поточний рік
        if parsed_date.year != now.year:
            raise ValueError(
                f"Дата інциденту має бути у <b>поточному {now.year} році</b>. Скарги за минулі роки не приймаються.")

        # --- КІНЕЦЬ НОВОЇ ВАЛІДАЦІЇ ---

    except ValueError as e:
        # Блок обробки помилок (залишається тим самим)
        await update.message.reply_text(
            f"❌ <b>Помилка:</b> {e}\n\nБудь ласка, спробуйте ще раз.",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        return States.COMPLAINT_DATETIME  # Повертаємо на той самий крок

async def complaint_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ ПІБ."""
    name_text = update.message.text.strip()
    keyboard = await get_cancel_keyboard("feedback_menu")

    # ВАЛІДАЦІЯ: (тільки літери, пробіли, дефіси, апостроф, від 5 символів)
    if not re.match(r"^[А-Яа-яЇїІіЄєҐґA-Za-z\s'-]{5,}$", name_text):
        await update.message.reply_text(
            f"❌ Будь ласка, введіть коректне ПІБ (тільки літери, довжина від 5 символів).",
            reply_markup=keyboard
        )
        return States.COMPLAINT_NAME # Повертаємо на той самий крок

    # Валідація пройдена:
    context.user_data['complaint_name'] = name_text
    logger.info(f"Name: {name_text}")

    await update.message.reply_text(
        MESSAGES['complaint_phone'],
        reply_markup=keyboard
    )
    return States.COMPLAINT_PHONE # <-- Новий стан


async def complaint_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ телефону. Збереження скарги."""
    phone_text = update.message.text.strip()
    keyboard = await get_cancel_keyboard("feedback_menu")

    # ВАЛІДАЦІЯ: (шукає 9 цифр, опціонально з +380 або 380 або 0 на початку)
    if not re.match(r"^(\+?38)?0\d{9}$", phone_text.replace(" ", "").replace("-", "")):
        await update.message.reply_text(
            f"❌ Не схоже на український номер телефону.\n\n"
            f"Будь ласка, введіть номер у форматі <code>0991234567</code> або <code>+380991234567</code>.",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        return States.COMPLAINT_PHONE # Повертаємо на той самий крок

    # Валідація пройдена:
    context.user_data['complaint_phone'] = phone_text
    logger.info(f"Phone: {phone_text}")

    # Збираємо всі дані з context
    complaint_data = {
        "problem": context.user_data.get('complaint_problem'),
        "route": context.user_data.get('complaint_route'),
        "board_number": context.user_data.get('complaint_board'),
        "incident_datetime": context.user_data.get('complaint_datetime'),
        "user_name": context.user_data.get('complaint_name'),
        "user_phone": context.user_data.get('complaint_phone')
    }

    try:
        service = TicketsService()
        # Cервіс `create_complaint_ticket` вже готовий приймати окремі 'user_name' та 'user_phone'
        result = await service.create_complaint_ticket(
            telegram_id=update.effective_user.id,
            complaint_data=complaint_data
        )

        if result['success']:
            keyboard = [
                # [InlineKeyboardButton("📊 Статус", callback_data=f"check:{result['ticket_id']}")], # (Розкоментуйте, якщо реалізуєте перевірку статусу)
                [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
            ]
            await update.message.reply_text(result['message'], reply_markup=InlineKeyboardMarkup(keyboard))
            logger.info(f"Complaint saved: {result['ticket_id']}")
        else:
            await update.message.reply_text(result['message'])
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ Сталася критична помилка при збереженні скарги.")

    context.user_data.clear() # Очищуємо context
    return ConversationHandler.END

