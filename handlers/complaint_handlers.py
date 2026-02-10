import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from services.tickets_service import TicketsService
from utils.logger import logger
from bot.states import States
from handlers.common import get_feedback_cancel_keyboard, safe_edit_prev_message


async def complaint_start_simplified(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = (
        "📨 <b>Форма подання скарги</b>\n\n"
        "Для детального розгляду Вашого звернення, будь ласка, надішліть "
        "<b>одним повідомленням</b> наступну інформацію:\n\n"
        "✍️ <b>1. Суть проблеми:</b> опишіть ситуацію детально.\n"
        "🚋 <b>2. Транспорт:</b> номер маршруту та бортовий номер (номер вагону/машини).\n"
        "🕒 <b>3. Час події:</b> дата та орієнтовний час.\n"
        "📧 <b>4. Контакти:</b> Ваше П.І.Б. та <b>E-mail</b> для надання відповіді."
    )
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")
    msg = await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='HTML')
    context.user_data['last_bot_msg_id'] = msg.message_id
    return States.COMPLAINT_AWAIT_TEXT


async def complaint_confirm_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує текст скарги і просить підтвердження"""
    await update.message.delete()

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

    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text=summary,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    return States.COMPLAINT_CONFIRMATION


async def complaint_save_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фінальне збереження скарги"""
    query = update.callback_query
    await query.answer()

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

        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text=result['message'],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]])
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text="❌ Помилка."
        )

    context.user_data.clear()
    return ConversationHandler.END