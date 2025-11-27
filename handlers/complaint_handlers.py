import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from services.tickets_service import TicketsService
from utils.logger import logger
from bot.states import States
from handlers.common import get_feedback_cancel_keyboard, safe_delete_prev_message


async def complaint_start_simplified(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = (
        "📝 <b>Надішліть одним повідомленням:</b>\n\n"
        "1. Опис проблеми\n2. Маршрут і номер транспорту\n3. Час події\n4. Ваші контакти (ПІБ, телефон)"
    )
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")
    msg = await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='HTML')
    context.user_data['last_bot_msg_id'] = msg.message_id
    return States.COMPLAINT_AWAIT_TEXT


async def complaint_confirm_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує текст скарги і просить підтвердження"""
    await update.message.delete()
    await safe_delete_prev_message(context, update.effective_chat.id)

    complaint_text = update.message.text
    context.user_data['complaint_text'] = complaint_text

    summary = (
        "🔍 <b>Перевірте текст Вашої скарги:</b>\n\n"
        f"<i>{complaint_text}</i>\n\n"
        "Чи все вірно?"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Так, надіслати", callback_data="complaint_confirm_send")],
        [InlineKeyboardButton("🔄 Написати заново", callback_data="complaint"),
         InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ]

    msg = await update.message.reply_text(
        text=summary,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    context.user_data['last_bot_msg_id'] = msg.message_id
    return States.COMPLAINT_CONFIRMATION


async def complaint_save_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фінальне збереження скарги"""
    query = update.callback_query
    await query.answer()
    await safe_delete_prev_message(context, update.effective_chat.id)

    text = context.user_data.get('complaint_text')

    # Формуємо структуру для TicketsService
    complaint_data = {
        "problem": text,
        "route": "N/A", "board_number": "N/A", "incident_datetime": "N/A",  # Спрощена форма
        "user_name": "Див. текст", "user_phone": "Див. текст", "user_email": "Див. текст"
    }

    try:
        service = TicketsService()
        result = await service.create_complaint_ticket(update.effective_user.id, complaint_data)

        await query.message.reply_text(
            result['message'],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]])
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.message.reply_text("❌ Помилка.")

    context.user_data.clear()
    return ConversationHandler.END