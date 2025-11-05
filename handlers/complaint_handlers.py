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
from handlers.common import get_feedback_cancel_keyboard # <-- Змінили назву


# Скомпілюємо список всіх валідних маршрутів
ALL_ROUTES = set(str(r) for r in ROUTES["tram"] + ROUTES["trolleybus"])
# ===== СКАРГИ =====

async def complaint_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок скарги"""
    logger.info(f"User {update.effective_user.id} started complaint")
    keyboard = await get_feedback_cancel_keyboard("feedback_menu") # <-- Використовуємо нову кнопку

    # Редагуємо повідомлення та ЗБЕРІГАЄМО ЙОГО ID
    sent_message = await update.callback_query.edit_message_text(
        text=MESSAGES['complaint_start'],
        reply_markup=keyboard
    )
    context.user_data['dialog_message_id'] = sent_message.message_id

    return States.COMPLAINT_PROBLEM


async def complaint_get_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання проблеми та запит маршруту."""
    await update.message.delete()  # 1. Видаляємо відповідь користувача
    context.user_data['complaint_problem'] = update.message.text
    logger.info(f"Problem: {update.message.text[:50]}")

    keyboard = await get_feedback_cancel_keyboard("feedback_menu")

    # 2. Видаляємо попереднє запитання бота
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete previous complaint message: {e}")

    # 3. Надсилаємо нове запитання та зберігаємо його ID
    sent_message = await update.message.reply_text(
        MESSAGES['complaint_route'],
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    context.user_data['dialog_message_id'] = sent_message.message_id

    return States.COMPLAINT_ROUTE


async def complaint_get_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ маршруту."""
    await update.message.delete()  # 1. Видаляємо відповідь користувача
    route_text = update.message.text.strip()
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")

    # 2. Видаляємо попереднє запитання бота
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete previous complaint message: {e}")

    # ВАЛІДАЦІЯ:
    if route_text not in ALL_ROUTES:
        sent_message = await update.message.reply_text( # 3. Надсилаємо (помилку)
            f"❌ Маршруту '<b>{route_text}</b>' не знайдено.\n\n"
            f"Будь ласка, введіть коректний номер (тільки цифри).",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        context.user_data['dialog_message_id'] = sent_message.message_id # 4. Зберігаємо ID
        return States.COMPLAINT_ROUTE # Повертаємо на той самий крок

    # Валідація пройдена:
    context.user_data['complaint_route'] = route_text
    logger.info(f"Route: {route_text}")

    sent_message = await update.message.reply_text( # 3. Надсилаємо (успіх)
        MESSAGES['complaint_board'],
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    context.user_data['dialog_message_id'] = sent_message.message_id # 4. Зберігаємо ID
    return States.COMPLAINT_BOARD


async def complaint_get_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ бортового номера."""
    await update.message.delete()  # 1. Видаляємо відповідь користувача
    board_text = update.message.text.strip()
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")

    # 2. Видаляємо попереднє запитання бота
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete previous complaint message: {e}")

    # ВАЛІДАЦІЯ: 4 цифри
    if not re.match(r"^\d{4}$", board_text):
        sent_message = await update.message.reply_text( # 3. Надсилаємо (помилку)
            f"❌ Невірний формат бортового номера.\n\n"
            f"Це має бути <b>4-значне число</b> (наприклад: <code>4015</code>). Спробуйте ще раз.",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        context.user_data['dialog_message_id'] = sent_message.message_id # 4. Зберігаємо ID
        return States.COMPLAINT_BOARD # Повертаємо на той самий крок

    # Валідація пройдена:
    context.user_data['complaint_board'] = board_text
    logger.info(f"Board: {board_text}")

    sent_message = await update.message.reply_text( # 3. Надсилаємо (успіх)
        MESSAGES['complaint_datetime'],
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    context.user_data['dialog_message_id'] = sent_message.message_id # 4. Зберігаємо ID
    return States.COMPLAINT_DATETIME


async def complaint_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ дати/часу."""
    await update.message.delete()  # 1. Видаляємо відповідь користувача
    datetime_text = update.message.text.strip()
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")

    # 2. Видаляємо попереднє запитання бота
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete previous complaint message: {e}")

    # ВАЛІДАЦІЯ:
    try:
        # (Тут ваш блок валідації дати, він правильний)
        if not re.match(r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$", datetime_text):
            raise ValueError("Невірний формат. Очікується <code>ДД.ММ.РРРР ГГ:ХХ</code>.")
        try:
            parsed_date = datetime.strptime(datetime_text, '%d.%m.%Y %H:%M')
        except ValueError:
            raise ValueError("Некоректна дата. Можливо, неіснуючий день або місяць?")
        now = datetime.now()
        if parsed_date > now:
            raise ValueError("Дата інциденту не може бути у майбутньому.")
        if parsed_date.year != now.year:
            raise ValueError(f"Дата інциденту має бути у <b>поточному {now.year} році</b>.")

    except ValueError as e:
        sent_message = await update.message.reply_text( # 3. Надсилаємо (помилку)
            f"❌ <b>Помилка:</b> {e}\n\nБудь ласка, спробуйте ще раз.",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        context.user_data['dialog_message_id'] = sent_message.message_id # 4. Зберігаємо ID
        return States.COMPLAINT_DATETIME  # Повертаємо на той самий крок

    # Валідація пройдена:
    context.user_data['complaint_datetime'] = datetime_text
    logger.info(f"DateTime: {datetime_text}")

    sent_message = await update.message.reply_text( # 3. Надсилаємо (успіх)
        MESSAGES['complaint_name'],
        reply_markup=keyboard
    )
    context.user_data['dialog_message_id'] = sent_message.message_id # 4. Зберігаємо ID
    return States.COMPLAINT_NAME  # Повертаємо на той самий крок

    # --- ПОЧАТОК ВИПРАВЛЕННЯ: Блок "Успіх" ---
    # Валідація пройдена:
    context.user_data['complaint_datetime'] = datetime_text
    logger.info(f"DateTime: {datetime_text}")

    # Запитуємо ПІБ
    await update.message.reply_text(
        MESSAGES['complaint_name'],
        reply_markup=keyboard
    )
    return States.COMPLAINT_NAME  # <-- Повертаємо НАСТУПНИЙ стан
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

async def complaint_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ ПІБ."""
    await update.message.delete()  # 1. Видаляємо відповідь користувача
    name_text = update.message.text.strip()
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")

    # 2. Видаляємо попереднє запитання бота
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete previous complaint message: {e}")

    # ВАЛІДАЦІЯ ПІБ:
    if not re.match(r"^[А-Яа-яЇїІіЄєҐґA-Za-z\s'-]{5,}$", name_text):
        sent_message = await update.message.reply_text( # 3. Надсилаємо (помилку)
            f"❌ Будь ласка, введіть коректне ПІБ (тільки літери, довжина від 5 символів).",
            reply_markup=keyboard
        )
        context.user_data['dialog_message_id'] = sent_message.message_id # 4. Зберігаємо ID
        return States.COMPLAINT_NAME # Повертаємо на той самий крок

    # Валідація пройдена:
    context.user_data['complaint_name'] = name_text
    logger.info(f"Name: {name_text}")

    sent_message = await update.message.reply_text( # 3. Надсилаємо (успіх)
        MESSAGES['complaint_phone'],
        reply_markup=keyboard
    )
    context.user_data['dialog_message_id'] = sent_message.message_id # 4. Зберігаємо ID
    return States.COMPLAINT_PHONE


async def complaint_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ телефону. Збереження скарги."""
    await update.message.delete()  # 1. Видаляємо відповідь користувача
    phone_text = update.message.text.strip()
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")

    # 2. Видаляємо попереднє запитання бота
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete final complaint message: {e}")

    # ВАЛІДАЦІЯ:
    if not re.match(r"^(\+?38)?0\d{9}$", phone_text.replace(" ", "").replace("-", "")):
        sent_message = await update.message.reply_text( # 3. Надсилаємо (помилку)
            f"❌ Не схоже на український номер телефону.\n\n"
            f"Введіть номер у форматі <code>0991234567</code>.",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        context.user_data['dialog_message_id'] = sent_message.message_id # 4. Зберігаємо ID
        return States.COMPLAINT_PHONE # Повертаємо на той самий крок

    # Валідація пройдена, збираємо дані (решта функції як у вас)
    context.user_data['complaint_phone'] = phone_text
    logger.info(f"Phone: {phone_text}")

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
        result = await service.create_complaint_ticket(
            telegram_id=update.effective_user.id,
            complaint_data=complaint_data
        )
        if result['success']:
            keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
            await update.message.reply_text(result['message'], reply_markup=InlineKeyboardMarkup(keyboard))
            logger.info(f"Complaint saved: {result['ticket_id']}")
        else:
            await update.message.reply_text(result['message'])
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ Сталася критична помилка при збереженні скарги.")

    context.user_data.clear()
    return ConversationHandler.END

