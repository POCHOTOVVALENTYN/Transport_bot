# handlers/suggestion_handlers.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler
from services.tickets_service import TicketsService
from handlers.common import get_back_keyboard
from bot.states import States
from utils.logger import logger


async def suggestion_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок збору пропозиції."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("💡 Опишіть вашу пропозицію:")
    return States.SUGGESTION_TEXT


async def suggestion_get_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання тексту пропозиції."""
    context.user_data['suggestion_text'] = update.message.text
    logger.info(f"Suggestion: {update.message.text[:50]}")
    await update.message.reply_text(
        "Ваші контакти (ПІБ, телефон) для зворотного зв'язку (за бажанням). \nАбо натисніть /skip, щоб пропустити.")
    return States.SUGGESTION_CONTACT


async def suggestion_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Збереження пропозиції з контактами."""
    contact = update.message.text
    await _save_suggestion(update, context, contact)
    return ConversationHandler.END


async def suggestion_skip_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Збереження пропозиції без контактів."""
    await _save_suggestion(update, context, "N/A")
    return ConversationHandler.END


async def _save_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE, contact: str):
    """Внутрішня функція збереження пропозиції."""
    try:
        service = TicketsService()
        result = await service.create_suggestion_ticket(
            telegram_id=update.effective_user.id,
            text=context.user_data.get('suggestion_text'),
            contact_info=contact
        )

        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]]
        await update.message.reply_text(result['message'], reply_markup=InlineKeyboardMarkup(keyboard))
        logger.info(f"Suggestion saved: {result.get('ticket_id')}")

    except Exception as e:
        logger.error(f"Error saving suggestion: {e}")
        await update.message.reply_text("❌ Сталася помилка при збереженні пропозиції.")

    context.user_data.clear()