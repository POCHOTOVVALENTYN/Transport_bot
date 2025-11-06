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
    """Отримання тексту пропозиції та запит про контакти."""
    await update.message.delete()
    context.user_data['suggestion_text'] = update.message.text
    logger.info(f"Suggestion text: {update.message.text[:50]}")

    keyboard = [
        [InlineKeyboardButton("🔘 Залишити контакти", callback_data="suggestion_contact:yes")],
        [InlineKeyboardButton("🔘 Відправити анонімно", callback_data="suggestion_contact:no")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete previous suggestion message: {e}")

    sent_message = await update.message.reply_text(
        text=MESSAGES['suggestion_ask_contact'],
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data['dialog_message_id'] = sent_message.message_id
    return States.SUGGESTION_ASK_CONTACT


async def suggestion_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Натиснуто 'Залишити контакти') Запитує ПІБ."""
    query = update.callback_query
    await query.answer()

    keyboard = await get_feedback_cancel_keyboard("feedback_menu")
    sent_message = await query.edit_message_text(
        text=MESSAGES['suggestion_name'],
        reply_markup=keyboard
    )
    context.user_data['dialog_message_id'] = sent_message.message_id
    return States.SUGGESTION_GET_NAME


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
    """Отримання та ВАЛІДАЦІЯ телефону. Збереження з контактами."""
    await update.message.delete()
    phone_text = update.message.text.strip()
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")

    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete final suggestion message: {e}")

    # ВАЛІДАЦІЯ ТЕЛЕФОНУ (як у скаргах)
    if not re.match(r"^(\+?38)?0\d{9}$", phone_text.replace(" ", "").replace("-", "")):
        sent_message = await update.message.reply_text(
            f"❌ Не схоже на український номер телефону.\n\n"
            f"Введіть номер у форматі <code>0991234567</code>.",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        context.user_data['dialog_message_id'] = sent_message.message_id
        return States.SUGGESTION_GET_PHONE

    # --- ПОЧАТОК ВИПРАВЛЕННЯ ---
    # Валідація пройдена:
    context.user_data['suggestion_phone'] = phone_text
    logger.info(f"Suggestion Phone: {phone_text}")

    # 1. Видаляємо попереднє запитання бота
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete final suggestion message: {e}")

    # 2. Надсилаємо нове запитання (про Email) та зберігаємо його ID
    sent_message = await update.message.reply_text(
        MESSAGES['suggestion_email'],
        reply_markup=keyboard
    )
    context.user_data['dialog_message_id'] = sent_message.message_id

    return States.SUGGESTION_EMAIL  # <-- Повертаємо новий стан
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---


async def suggestion_save_anonymously(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Натиснуто 'Відправити анонімно') Збереження без контактів."""
    query = update.callback_query
    await query.answer()

    suggestion_data = {
        "text": context.user_data.get('suggestion_text'),
        "user_name": "Анонімно",
        "user_phone": "N/A"
    }

    # Видаляємо останнє запитання ("Залишити контакти?")
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete suggestion ask message: {e}")

    await _save_suggestion(query, context, suggestion_data)
    return ConversationHandler.END


async def _save_suggestion(update, context: ContextTypes.DEFAULT_TYPE, suggestion_data: dict):
    """Внутрішня функція збереження пропозиції."""

    if hasattr(update, 'message') and update.message is not None:
        reply_func = update.message.reply_text
    else:
        # Це CallbackQuery, але ми не можемо .edit_message_text(), бо ми видалили повідомлення
        reply_func = update.message.reply_text

    try:
        service = TicketsService()
        result = await service.create_suggestion_ticket(
            telegram_id=update.effective_user.id,
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
        await reply_func("❌ Сталася помилка при збереженні пропозиції.")

    context.user_data.clear()


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