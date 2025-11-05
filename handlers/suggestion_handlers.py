import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler
from telegram.constants import ParseMode

from services.tickets_service import TicketsService
from handlers.common import get_back_keyboard, get_cancel_keyboard
from bot.states import States
from utils.logger import logger
from config.messages import MESSAGES


async def suggestion_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок збору пропозиції."""
    query = update.callback_query
    await query.answer()

    keyboard = await get_cancel_keyboard("feedback_menu")
    await query.edit_message_text(
        text=MESSAGES['suggestion_start'],
        reply_markup=keyboard
    )
    return States.SUGGESTION_TEXT


async def suggestion_ask_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання тексту пропозиції та запит про контакти."""
    context.user_data['suggestion_text'] = update.message.text
    logger.info(f"Suggestion text: {update.message.text[:50]}")

    keyboard = [
        [InlineKeyboardButton("🔘 Залишити контакти", callback_data="suggestion_contact:yes")],
        [InlineKeyboardButton("🔘 Відправити анонімно", callback_data="suggestion_contact:no")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    await update.message.reply_text(
        text=MESSAGES['suggestion_ask_contact'],
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return States.SUGGESTION_ASK_CONTACT


async def suggestion_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Натиснуто 'Залишити контакти') Запитує ПІБ."""
    query = update.callback_query
    await query.answer()

    keyboard = await get_cancel_keyboard("feedback_menu")
    await query.edit_message_text(
        text=MESSAGES['suggestion_name'],
        reply_markup=keyboard
    )
    return States.SUGGESTION_GET_NAME


async def suggestion_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ ПІБ."""
    name_text = update.message.text.strip()
    keyboard = await get_cancel_keyboard("feedback_menu")

    # ВАЛІДАЦІЯ ПІБ (як у скаргах)
    if not re.match(r"^[А-Яа-яЇїІіЄєҐґA-Za-z\s'-]{5,}$", name_text):
        await update.message.reply_text(
            f"❌ Будь ласка, введіть коректне ПІБ (тільки літери, довжина від 5 символів).",
            reply_markup=keyboard
        )
        return States.SUGGESTION_GET_NAME # Повертаємо на той самий крок

    context.user_data['suggestion_name'] = name_text
    logger.info(f"Suggestion Name: {name_text}")

    await update.message.reply_text(
        text=MESSAGES['suggestion_phone'],
        reply_markup=keyboard
    )
    return States.SUGGESTION_GET_PHONE


async def suggestion_save_with_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ телефону. Збереження з контактами."""
    phone_text = update.message.text.strip()
    keyboard = await get_cancel_keyboard("feedback_menu")

    # ВАЛІДАЦІЯ ТЕЛЕФОНУ (як у скаргах)
    if not re.match(r"^(\+?38)?0\d{9}$", phone_text.replace(" ", "").replace("-", "")):
        await update.message.reply_text(
            f"❌ Не схоже на український номер телефону.\n\n"
            f"Введіть номер у форматі <code>0991234567</code>.",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        return States.SUGGESTION_GET_PHONE # Повертаємо на той самий крок

    context.user_data['suggestion_phone'] = phone_text
    logger.info(f"Suggestion Phone: {phone_text}")

    # Збираємо дані
    suggestion_data = {
        "text": context.user_data.get('suggestion_text'),
        "user_name": context.user_data.get('suggestion_name'),
        "user_phone": context.user_data.get('suggestion_phone')
    }

    await _save_suggestion(update, context, suggestion_data)
    return ConversationHandler.END


async def suggestion_save_anonymously(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Натиснуто 'Відправити анонімно') Збереження без контактів."""
    query = update.callback_query
    await query.answer()

    suggestion_data = {
        "text": context.user_data.get('suggestion_text'),
        "user_name": "Анонімно",
        "user_phone": "N/A"
    }

    # Використовуємо update від query для відповіді
    await _save_suggestion(query, context, suggestion_data)
    return ConversationHandler.END


async def _save_suggestion(update, context: ContextTypes.DEFAULT_TYPE, suggestion_data: dict):
    """Внутрішня функція збереження пропозиції."""

    # Визначаємо, як відповідати (текстом чи редагуванням кнопки)
    if hasattr(update, 'message') and update.message is not None:
        reply_func = update.message.reply_text
    else: # Це CallbackQuery
        reply_func = update.edit_message_text

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