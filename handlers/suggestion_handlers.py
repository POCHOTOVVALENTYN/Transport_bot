import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from services.tickets_service import TicketsService
from handlers.common import get_feedback_cancel_keyboard, safe_delete_prev_message
from bot.states import States
from utils.logger import logger
from config.messages import MESSAGES


# === ДОПОМІЖНІ ===
async def _ask_next_step(update, context, text, keyboard_markup=None):
    """Відправляє питання і зберігає його ID"""
    if not keyboard_markup:
        keyboard_markup = await get_feedback_cancel_keyboard("feedback_menu")

    msg = await update.message.reply_text(text=text, reply_markup=keyboard_markup, parse_mode=ParseMode.HTML)
    context.user_data['last_bot_msg_id'] = msg.message_id


# === ХЕНДЛЕРИ ===

async def suggestion_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = await get_feedback_cancel_keyboard("feedback_menu")
    msg = await query.edit_message_text(text=MESSAGES['suggestion_start'], reply_markup=keyboard)
    context.user_data['last_bot_msg_id'] = msg.message_id
    return States.SUGGESTION_TEXT


async def suggestion_ask_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.delete()
    await safe_delete_prev_message(context, update.effective_chat.id)

    context.user_data['suggestion_text'] = update.message.text
    # Переходимо до запиту імені
    await _ask_next_step(update, context, MESSAGES['suggestion_name'])
    return States.SUGGESTION_GET_NAME


async def suggestion_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.delete()
    await safe_delete_prev_message(context, update.effective_chat.id)

    name = update.message.text.strip()
    if len(name) < 5:
        # Помилка - питаємо знову
        await _ask_next_step(update, context, "❌ П.І.Б. надто коротке. Введіть ще раз:")
        return States.SUGGESTION_GET_NAME

    context.user_data['suggestion_name'] = name
    await _ask_next_step(update, context, MESSAGES['suggestion_phone'])
    return States.SUGGESTION_GET_PHONE


async def suggestion_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.delete()
    await safe_delete_prev_message(context, update.effective_chat.id)

    phone = update.message.text.strip()
    # (Тут можна додати regex валідацію телефону, якщо треба)

    context.user_data['suggestion_phone'] = phone

    # Кнопка "Пропустити" для Email
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Пропустити Email", callback_data="suggestion_skip_email")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ])

    msg = await update.message.reply_text(MESSAGES['suggestion_email'], reply_markup=kb)
    context.user_data['last_bot_msg_id'] = msg.message_id
    return States.SUGGESTION_EMAIL


# === ЕТАП ПІДТВЕРДЖЕННЯ (Новий) ===

async def suggestion_check_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Формує звіт і просить підтвердження"""

    # Визначаємо джерело (текст чи кнопка "Пропустити")
    if update.callback_query:
        await update.callback_query.answer()
        email = "Не вказано"
        # Редагуємо повідомлення, якщо це колбек
        msg_func = update.callback_query.edit_message_text
    else:
        await update.message.delete()
        await safe_delete_prev_message(context, update.effective_chat.id)
        email = update.message.text.strip()
        msg_func = update.message.reply_text

    context.user_data['suggestion_email'] = email

    summary = (
        f"🔍 <b>Перевірте Вашу пропозицію:</b>\n\n"
        f"📝 <b>Текст:</b> {context.user_data.get('suggestion_text')}\n"
        f"👤 <b>Ім'я:</b> {context.user_data.get('suggestion_name')}\n"
        f"📞 <b>Телефон:</b> {context.user_data.get('suggestion_phone')}\n"
        f"📧 <b>Email:</b> {email}"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Все вірно, надіслати", callback_data="suggestion_confirm_send")],
        [InlineKeyboardButton("🔄 Заповнити заново", callback_data="suggestion"),
         InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ]

    msg = await msg_func(text=summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    # Якщо це був reply_text, треба зберегти ID. Якщо edit - він не змінюється, але оновити не завадить.
    if hasattr(msg, 'message_id'):
        context.user_data['last_bot_msg_id'] = msg.message_id

    return States.SUGGESTION_CONFIRMATION


async def suggestion_save_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фінальне збереження"""
    query = update.callback_query
    await query.answer()
    await safe_delete_prev_message(context, update.effective_chat.id)

    data = {
        "text": context.user_data.get('suggestion_text'),
        "user_name": context.user_data.get('suggestion_name'),
        "user_phone": context.user_data.get('suggestion_phone'),
        "user_email": context.user_data.get('suggestion_email')
    }

    try:
        service = TicketsService()
        result = await service.create_suggestion_ticket(update.effective_user.id, data)

        await query.message.reply_text(
            result['message'],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]])
        )
    except Exception as e:
        logger.error(f"Save error: {e}")
        await query.message.reply_text("❌ Помилка збереження.")

    context.user_data.clear()
    return ConversationHandler.END