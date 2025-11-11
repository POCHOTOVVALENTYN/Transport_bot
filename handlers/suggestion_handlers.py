import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler
from telegram.constants import ParseMode

from services.tickets_service import TicketsService
from handlers.common import get_back_keyboard, get_feedback_cancel_keyboard  # <-- Використовуємо нову кнопку
from bot.states import States
from utils.logger import logger
from config.messages import MESSAGES


async def suggestion_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок збору пропозиції."""
    query = update.callback_query
    await query.answer()

    keyboard = await get_feedback_cancel_keyboard("feedback_menu")
    sent_message = await query.edit_message_text(
        text=MESSAGES['suggestion_start'],
        reply_markup=keyboard
    )
    context.user_data['dialog_message_id'] = sent_message.message_id
    return States.SUGGESTION_TEXT


async def suggestion_ask_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання тексту пропозиції та ЗАПИТ ПРО ПІБ (анонімність видалено)."""
    await update.message.delete()
    context.user_data['suggestion_text'] = update.message.text
    logger.info(f"Suggestion text: {update.message.text[:50]}")

    keyboard = await get_feedback_cancel_keyboard("feedback_menu")

    try:
        # Видаляємо повідомлення "Опишіть вашу пропозицію"
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete previous suggestion message: {e}")

    # Одразу запитуємо ПІБ
    sent_message = await update.message.reply_text(
        text=MESSAGES['suggestion_name'], # Використовуємо текст із config/messages.py
        reply_markup=keyboard
    )
    context.user_data['dialog_message_id'] = sent_message.message_id

    # Одразу переходимо до стану отримання імені
    return States.SUGGESTION_GET_NAME

async def suggestion_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Натиснуто 'Залишити контакти') Запитує ПІБ."""
    # Ця функція викликається з suggestion_ask_contact
    await update.message.delete()
    name_text = update.message.text.strip()
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")

    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete previous suggestion message: {e}")

    # ВАЛІДАЦІЯ ПІБ (як у скаргах)
    if not re.match(r"^[А-Яа-яЇїІіЄєҐґA-Za-z\s'-]{5,}$", name_text):
        sent_message = await update.message.reply_text(
            f"❌ Будь ласка, введіть коректне ПІБ (тільки літери, довжина від 5 символів).",
            reply_markup=keyboard
        )
        context.user_data['dialog_message_id'] = sent_message.message_id
        return States.SUGGESTION_GET_NAME # Повертаємо на той самий крок

    context.user_data['suggestion_name'] = name_text
    logger.info(f"Suggestion Name: {name_text}")

    sent_message = await update.message.reply_text(
        text=MESSAGES['suggestion_phone'],
        reply_markup=keyboard
    )
    context.user_data['dialog_message_id'] = sent_message.message_id
    return States.SUGGESTION_GET_PHONE

async def suggestion_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ ПІБ."""
    await update.message.delete()
    name_text = update.message.text.strip()
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")

    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete previous suggestion message: {e}")

    # ВАЛІДАЦІЯ ПІБ (як у скаргах)
    if not re.match(r"^[А-Яа-яЇїІіЄєҐґA-Za-z\s'-]{5,}$", name_text):
        sent_message = await update.message.reply_text(
            f"❌ Будь ласка, введіть коректне ПІБ (тільки літери, довжина від 5 символів).",
            reply_markup=keyboard
        )
        context.user_data['dialog_message_id'] = sent_message.message_id
        return States.SUGGESTION_GET_NAME

    context.user_data['suggestion_name'] = name_text
    logger.info(f"Suggestion Name: {name_text}")

    sent_message = await update.message.reply_text(
        text=MESSAGES['suggestion_phone'],
        reply_markup=keyboard
    )
    context.user_data['dialog_message_id'] = sent_message.message_id
    return States.SUGGESTION_GET_PHONE




async def suggestion_get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ телефону. Запит Email."""
    await update.message.delete()
    phone_text = update.message.text.strip()

    # 1. Створюємо список кнопок (це звичайний Python list)
    keyboard_markup = [
        [InlineKeyboardButton("➡️ Пропустити", callback_data="suggestion_skip_email")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    # 2. Створюємо об'єкт клавіатури (це об'єкт InlineKeyboardMarkup)
    keyboard = InlineKeyboardMarkup(keyboard_markup)

    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete previous suggestion message: {e}")

    # ВАЛІДАЦІЯ ТЕЛЕФОНУ
    if not re.match(r"^(\+?38)?0\d{9}$", phone_text.replace(" ", "").replace("-", "")):
        sent_message = await update.message.reply_text(
            f"❌ Не схоже на український номер телефону.\n\n"
            f"Введіть номер у форматі <code>0991234567</code>.",

            # --- ВИПРАВЛЕННЯ ЙМОВІРНО ТУТ ---
            # Переконайтеся, що тут 'keyboard', а НЕ 'keyboard_markup'
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        context.user_data['dialog_message_id'] = sent_message.message_id
        return States.SUGGESTION_GET_PHONE

    # Валідація пройдена:
    context.user_data['suggestion_phone'] = phone_text
    logger.info(f"Suggestion Phone: {phone_text}")

    # (Цей блок try/except був у вашому коді, я його залишив, хоча він може бути зайвим,
    # оскільки ми вже видалили повідомлення вище)
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete final suggestion message: {e}")  # Це 'Message not found' з вашого логу

    # 2. Надсилаємо нове запитання (про Email) та зберігаємо його ID
    sent_message = await update.message.reply_text(
        MESSAGES['suggestion_email'],

        # --- АБО ВИПРАВЛЕННЯ ЙМОВІРНО ТУТ ---
        # Переконайтеся, що тут 'keyboard', а НЕ 'keyboard_markup'
        reply_markup=keyboard
    )
    context.user_data['dialog_message_id'] = sent_message.message_id

    return States.SUGGESTION_EMAIL


async def _save_suggestion(update, context: ContextTypes.DEFAULT_TYPE, suggestion_data: dict):
    """Внутрішня функція збереження пропозиції."""

    # --- ПОЧАТОК ВИПРАВЛЕННЯ ---
    # Ми очікуємо 'update' різного типу:
    # 1. Update (якщо викликано з ...with_email)
    # 2. CallbackQuery (якщо викликано з ...anonymously)

    if isinstance(update, Update):
        # Випадок 1: Це повний об'єкт Update (з MessageHandler)
        reply_func = update.message.reply_text
        user_id = update.effective_user.id
    else:
        # Випадок 2: Це об'єкт CallbackQuery (з CallbackQueryHandler)
        reply_func = update.message.reply_text
        user_id = update.from_user.id
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

    try:
        service = TicketsService()
        result = await service.create_suggestion_ticket(
            telegram_id=user_id,  # <-- Тепер тут правильний ID
            suggestion_data=suggestion_data
        )

        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]]
        await reply_func(
            text=result['message'],
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        logger.info(f"Suggestion saved: {result.get('ticket_id')}")

    except Exception as e:
        logger.error(f"Error saving suggestion: {e}")
        # Ця функція тепер також гарантовано спрацює
        await reply_func("❌ Сталася помилка при збереженні пропозиції.")

    context.user_data.clear()


async def suggestion_save_skip_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Натиснуто 'Пропустити' на етапі Email) Збереження без email."""
    query = update.callback_query
    await query.answer()

    # 1. Видаляємо запитання про Email
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete suggestion email message: {e}")

    # 2. Збираємо дані (email буде відсутній)
    suggestion_data = {
        "text": context.user_data.get('suggestion_text'),
        "user_name": context.user_data.get('suggestion_name'),
        "user_phone": context.user_data.get('suggestion_phone'),
        "user_email": "N/A"  # Вказуємо, що email пропущено
    }

    logger.info("Suggestion saving (Email skipped)")

    # 3. Викликаємо ту саму функцію збереження, яку ми виправили минулого разу
    await _save_suggestion(query, context, suggestion_data)
    return ConversationHandler.END


async def suggestion_save_with_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ email. Збереження з контактами."""
    await update.message.delete()  # 1. Видаляємо відповідь користувача (email)
    email_text = update.message.text.strip()
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")

    # 2. Видаляємо попереднє запитання бота
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete final suggestion message: {e}")

    # ВАЛІДАЦІЯ EMAIL (проста):
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email_text):
        sent_message = await update.message.reply_text(
            f"❌ Не схоже на email адресу.\n\n"
            f"Будь ласка, введіть коректний email (наприклад: <code>example@gmail.com</code>).",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        context.user_data['dialog_message_id'] = sent_message.message_id
        return States.SUGGESTION_EMAIL # Повертаємо на той самий крок

    # Валідація пройдена, збираємо дані
    context.user_data['suggestion_email'] = email_text
    logger.info(f"Suggestion Email: {email_text}")

    suggestion_data = {
        "text": context.user_data.get('suggestion_text'),
        "user_name": context.user_data.get('suggestion_name'),
        "user_phone": context.user_data.get('suggestion_phone'),
        "user_email": context.user_data.get('suggestion_email') # <-- Нове поле
    }

    await _save_suggestion(update, context, suggestion_data)
    return ConversationHandler.END