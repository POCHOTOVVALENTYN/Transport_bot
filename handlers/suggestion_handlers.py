import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from services.tickets_service import TicketsService
from handlers.common import get_feedback_cancel_keyboard, safe_edit_prev_message
from bot.states import States
from utils.logger import logger
from config.messages import MESSAGES

# Імпортуємо загальні валідатори
from handlers.complaint_handlers import clean_phone, is_valid_email
from handlers.thanks_handlers import validate_name


# === ДОПОМІЖНІ ===
async def _ask_next_step(update, context, text, keyboard_markup=None):
    """Відправляє питання і зберігає його ID"""
    if not keyboard_markup:
        keyboard_markup = await get_feedback_cancel_keyboard("feedback_menu")

    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text=text,
        reply_markup=keyboard_markup,
        parse_mode=ParseMode.HTML
    )


# === ХЕНДЛЕРИ ===

async def suggestion_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Очищення старих даних
    context.user_data.pop('suggestion_text', None)
    context.user_data.pop('suggestion_name', None)
    context.user_data.pop('suggestion_phone', None)
    context.user_data.pop('suggestion_email', None)

    keyboard = await get_feedback_cancel_keyboard("feedback_menu")
    msg = await query.edit_message_text(text=MESSAGES['suggestion_start'], reply_markup=keyboard)
    context.user_data['last_bot_msg_id'] = msg.message_id
    return States.SUGGESTION_TEXT


async def suggestion_ask_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.delete()

    text = update.message.text.strip()
    if len(text) < 10:
        await _ask_next_step(
            update,
            context,
            "⚠️ <b>Опис пропозиції занадто короткий!</b>\n\nБудь ласка, опишіть Вашу ідею детальніше (мінімум 10 символів):"
        )
        return States.SUGGESTION_TEXT

    context.user_data['suggestion_text'] = text
    # Переходимо до запиту імені
    await _ask_next_step(update, context, MESSAGES['suggestion_name'])
    return States.SUGGESTION_GET_NAME


async def suggestion_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.delete()

    name = update.message.text.strip()
    if not validate_name(name):
        # Помилка - питаємо знову
        await _ask_next_step(
            update,
            context,
            "⚠️ <b>Некоректне ім'я!</b>\n\nБудь ласка, введіть П.І.Б. ще раз (лише літери, дефіс та апостроф, мінімум 5 символів):"
        )
        return States.SUGGESTION_GET_NAME

    context.user_data['suggestion_name'] = name
    await _ask_next_step(update, context, MESSAGES['suggestion_phone'])
    return States.SUGGESTION_GET_PHONE


async def suggestion_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.delete()

    raw_phone = update.message.text.strip()
    phone = clean_phone(raw_phone)
    if not phone:
        await _ask_next_step(
            update,
            context,
            "⚠️ <b>Некоректний формат телефону!</b>\n\nБудь ласка, введіть дійсний номер (наприклад: 0951234567):"
        )
        return States.SUGGESTION_GET_PHONE

    context.user_data['suggestion_phone'] = phone

    # Клавіатура для Email (обов'язково)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ])

    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text="📧 <b>Крок 4: E-mail для зв'язку</b>\n\nБудь ласка, введіть Вашу адресу електронної пошти (обов'язково):",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return States.SUGGESTION_EMAIL


# === ЕТАП ПІДТВЕРДЖЕННЯ ===

async def suggestion_check_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Формує звіт і просить підтвердження"""
    is_callback = update.callback_query is not None

    if is_callback:
        query = update.callback_query
        await query.answer("Цей крок є обов'язковим!", show_alert=True)
        return States.SUGGESTION_EMAIL

    await update.message.delete()
    raw_email = update.message.text.strip()

    if not is_valid_email(raw_email):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
        ])
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text="⚠️ <b>Некоректний формат E-mail!</b>\n\nБудь ласка, введіть дійсну адресу (наприклад: user@example.com):",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        return States.SUGGESTION_EMAIL

    email = raw_email
    context.user_data['suggestion_email'] = email
    return await suggestion_show_confirm(update, context)


async def suggestion_ask_response_need(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Запит чи потрібна відповідь на пропозицію (застарілий крок, залишено для сумісності)"""
    return await suggestion_show_confirm(update, context)


async def suggestion_response_need_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка вибору потреби у відповіді (застарілий крок)"""
    return await suggestion_show_confirm(update, context)


async def suggestion_home_address_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання домашньої адреси (застарілий крок)"""
    return await suggestion_show_confirm(update, context)


async def suggestion_show_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує екран підтвердження зведених даних"""
    email = context.user_data.get('suggestion_email')

    summary = (
        f"🔍 <b>Перевірте Вашу пропозицію:</b>\n\n"
        f"📝 <b>Текст:</b> {context.user_data.get('suggestion_text')}\n"
        f"👤 <b>Ім'я:</b> {context.user_data.get('suggestion_name')}\n"
        f"📞 <b>Телефон:</b> {context.user_data.get('suggestion_phone')}\n"
        f"📧 <b>Email:</b> {email}\n"
    )

    summary += "\nУсе правильно?"

    keyboard = [
        [InlineKeyboardButton("✅ Все вірно, надіслати", callback_data="suggestion_confirm_send")],
        [InlineKeyboardButton("🔄 Заповнити заново", callback_data="suggestion"),
         InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ]

    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text=summary,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return States.SUGGESTION_CONFIRMATION


async def suggestion_save_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фінальне збереження"""
    query = update.callback_query
    await query.answer()

    data = {
        "text": context.user_data.get('suggestion_text'),
        "user_name": context.user_data.get('suggestion_name'),
        "user_phone": context.user_data.get('suggestion_phone'),
        "user_email": context.user_data.get('suggestion_email'),
        "need_response": context.user_data.get('suggestion_need_response', 'no'),
        "home_address": context.user_data.get('suggestion_home_address')
    }

    try:
        service = TicketsService()
        result = await service.create_suggestion_ticket(update.effective_user.id, data)

        # Надсилаємо картку модерації адмінам
        from handlers.admin_handlers import send_moderation_card_to_admins
        await send_moderation_card_to_admins(context.bot, result['ticket_id'])

        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text=result['message'],
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Зрозуміло 👍", callback_data="delete_message")],
                [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
            ]),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Save error: {e}")
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text="❌ Помилка збереження."
        )

    # Очищення сесії
    context.user_data.pop('suggestion_text', None)
    context.user_data.pop('suggestion_name', None)
    context.user_data.pop('suggestion_phone', None)
    context.user_data.pop('suggestion_email', None)
    context.user_data.pop('suggestion_need_response', None)
    context.user_data.pop('suggestion_home_address', None)
    return ConversationHandler.END