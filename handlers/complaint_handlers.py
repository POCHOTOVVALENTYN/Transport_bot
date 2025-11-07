import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from services.tickets_service import TicketsService
from utils.logger import logger
from bot.states import States
from handlers.common import get_feedback_cancel_keyboard  # <-- Використовуємо стару кнопку


# ===== СКАРГИ (НОВА СПРОЩЕНА ВЕРСІЯ) =====

async def complaint_start_simplified(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Початок скарги (спрощена версія).
    Надсилає одне повідомлення з інструкцією.
    """
    query = update.callback_query
    await query.answer()
    logger.info(f"User {update.effective_user.id} started simplified complaint")

    # Ваш новий текст інструкції
    text = (
        "📝 За допомогою клавіатури Вашого мобільного пристрою, будь ласка, надішліть одним повідомленням таку інформацію:\n\n"
        "1️⃣ Короткий опис ситуації або проблеми.\n\n"
        "2️⃣ Номер маршруту (трамвая чи тролейбуса).\n\n"
        "3️⃣ Бортовий номер транспорту (якщо відомий).\n\n"
        "4️⃣ Дату та орієнтовний час інциденту.\n\n"
        "5️⃣ Ваші прізвище, ім’я та по батькові.\n\n"
        "6️⃣ Контактний номер телефону для зворотного зв’язку.\n\n"
        "7️⃣ Електронну адресу (для отримання офіційної відповіді).\n\n"
    )

    keyboard = await get_feedback_cancel_keyboard("feedback_menu")

    # Редагуємо повідомлення та ЗБЕРІГАЄМО ЙОГО ID
    sent_message = await query.edit_message_text(
        text=text,
        reply_markup=keyboard
    )
    context.user_data['dialog_message_id'] = sent_message.message_id

    # Переходимо в єдиний стан очікування тексту
    return States.COMPLAINT_AWAIT_TEXT


async def complaint_save_simplified(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отримує єдине повідомлення зі скаргою та зберігає його.
    """
    await update.message.delete()  # 1. Видаляємо відповідь користувача
    full_complaint_text = update.message.text
    logger.info(f"Simplified complaint received: {full_complaint_text[:50]}")

    # 2. Видаляємо попереднє запитання бота (інструкцію)
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete simplified complaint message: {e}")

    # 3. Готуємо дані для збереження
    # Всю інформацію кладемо в 'problem', решту позначаємо як 'N/A'
    # (оператор в Google Sheets побачить все в одному полі)
    complaint_data = {
        "problem": full_complaint_text,
        "route": "N/A",
        "board_number": "N/A",
        "incident_datetime": "N/A",
        "user_name": "Див. опис скарги",
        "user_phone": "Див. опис скарги",
        "user_email": "Див. опис скарги"
    }

    # 4. Зберігаємо скаргу
    try:
        service = TicketsService()
        result = await service.create_complaint_ticket(
            telegram_id=update.effective_user.id,
            complaint_data=complaint_data
        )
        if result['success']:
            keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
            await update.message.reply_text(result['message'], reply_markup=InlineKeyboardMarkup(keyboard))
            logger.info(f"Simplified complaint saved: {result['ticket_id']}")
        else:
            await update.message.reply_text(result['message'])
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ Сталася критична помилка при збереженні скарги.")

    context.user_data.clear()
    return ConversationHandler.END