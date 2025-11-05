import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from services.tickets_service import TicketsService
from bot.states import States
from utils.logger import logger
from handlers.common import get_feedback_cancel_keyboard  # <-- Використовуємо нову кнопку
from config.settings import ROUTES

ALL_ROUTES = set(str(r) for r in ROUTES["tram"] + ROUTES["trolleybus"])


async def thanks_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок подяки."""
    query = update.callback_query
    await query.answer()

    keyboard = await get_feedback_cancel_keyboard("feedback_menu")
    sent_message = await query.edit_message_text(
        text="❤️ Чудово! Будь ласка, опишіть, за що ви вдячні:",
        reply_markup=keyboard
    )
    context.user_data['dialog_message_id'] = sent_message.message_id
    return States.THANKS_PROBLEM


async def thanks_ask_specific(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання тексту подяки та запитання про конкретику."""
    await update.message.delete()
    context.user_data['thanks_text'] = update.message.text
    logger.info(f"Thanks text: {update.message.text[:50]}")

    keyboard = [
        [InlineKeyboardButton("🔘 Так, конкретного", callback_data="thanks_specific:yes")],
        [InlineKeyboardButton("🔘 Ні, це загальна подяка", callback_data="thanks_specific:no")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete previous thanks message: {e}")

    sent_message = await update.message.reply_text(
        "Ця подяка стосується конкретного водія/маршруту?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data['dialog_message_id'] = sent_message.message_id
    return States.THANKS_ASK_SPECIFIC


async def thanks_get_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запитує маршрут (якщо подяка конкретна)."""
    query = update.callback_query
    await query.answer()

    context.user_data['thanks_route'] = None
    context.user_data['thanks_board'] = None

    keyboard = await get_feedback_cancel_keyboard("feedback_menu")
    sent_message = await query.edit_message_text(
        text="🚃 Вкажіть номер маршруту (тільки цифри, наприклад: <code>7</code>):",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    context.user_data['dialog_message_id'] = sent_message.message_id
    return States.THANKS_ROUTE


async def thanks_get_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та ВАЛІДАЦІЯ маршруту."""
    await update.message.delete()
    route_text = update.message.text.strip()
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")

    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete previous thanks message: {e}")

    if route_text not in ALL_ROUTES:
        sent_message = await update.message.reply_text(
            f"❌ Маршруту '<b>{route_text}</b>' не знайдено.\n\n"
            f"Будь ласка, введіть коректний номер (тільки цифри).",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        context.user_data['dialog_message_id'] = sent_message.message_id
        return States.THANKS_ROUTE

    context.user_data['thanks_route'] = route_text
    logger.info(f"Thanks Route: {route_text}")

    sent_message = await update.message.reply_text(
        text="🔢 Вкажіть бортовий номер (4-значне число, наприклад: <code>4015</code>):",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    context.user_data['dialog_message_id'] = sent_message.message_id
    return States.THANKS_BOARD


async def thanks_ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання бортового номера та запит про ім'я."""

    # Визначаємо, як прийшло оновлення (текстом чи кнопкою)
    if update.message:
        await update.message.delete()  # Видаляємо відповідь користувача
        board_text = update.message.text.strip()
        keyboard = await get_feedback_cancel_keyboard("feedback_menu")

        try:  # Видаляємо запитання про бортовий номер
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=context.user_data['dialog_message_id']
            )
        except Exception as e:
            logger.warning(f"Could not delete previous thanks message: {e}")

        # ВАЛІДАЦІЯ: 4 цифри
        if not re.match(r"^\d{4}$", board_text):
            sent_message = await update.message.reply_text(
                f"❌ Невірний формат бортового номера.\n\n"
                f"Це має бути <b>4-значне число</b> (наприклад: <code>4015</code>). Спробуйте ще раз.",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            context.user_data['dialog_message_id'] = sent_message.message_id
            return States.THANKS_BOARD  # Повертаємо на той самий крок

        context.user_data['thanks_board'] = board_text
        logger.info(f"Thanks Board: {board_text}")

    elif update.callback_query:  # Це відповідь "Ні, це загальна"
        await update.callback_query.answer()
        context.user_data['thanks_route'] = None
        context.user_data['thanks_board'] = None
        # Немає повідомлення користувача, але є `dialog_message_id` (запитання Так/Ні)
        # Ми не будемо його видаляти, а відредагуємо

    keyboard_ask_name = [
        [InlineKeyboardButton("🔘 Так, вказати ім'я", callback_data="thanks_name:yes")],
        [InlineKeyboardButton("🔘 Залишитися анонімним", callback_data="thanks_name:no")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    text = "Дякуємо! Бажаєте вказати своє ім'я (щоб ми знали, хто дякує)?"

    if update.callback_query:
        sent_message = await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard_ask_name)
        )
    else:
        sent_message = await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard_ask_name)
        )

    context.user_data['dialog_message_id'] = sent_message.message_id
    return States.THANKS_ASK_NAME


async def thanks_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запитує ПІБ, якщо користувач погодився."""
    query = update.callback_query
    await query.answer()

    keyboard = await get_feedback_cancel_keyboard("feedback_menu")
    sent_message = await query.edit_message_text(
        text="👤 Вкажіть ваше ПІБ (наприклад: Писаренко Олег Анатолійович):",
        reply_markup=keyboard
    )
    context.user_data['dialog_message_id'] = sent_message.message_id
    return States.THANKS_GET_NAME


async def thanks_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Зберігає подяку (анонімно або з ім'ям)."""
    user_name = "Анонім"

    try:
        # Видаляємо останнє повідомлення (або відповідь, або запитання)
        if update.message:
            await update.message.delete()
            name_text = update.message.text.strip()
            if re.match(r"^[А-Яа-яЇїІіЄєҐґA-Za-z\s'-]{5,}$", name_text):
                user_name = name_text
            else:
                user_name = "Анонім (ввід не розпізнано)"

        elif update.callback_query:  # Користувач натиснув "Залишитися анонімним"
            await update.callback_query.answer()

        # Видаляємо останнє запитання бота
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete final thanks messages: {e}")

    # Збираємо дані
    thanks_data = {
        "text": context.user_data.get('thanks_text'),
        "route": context.user_data.get('thanks_route'),
        "board_number": context.user_data.get('thanks_board'),
        "user_name": user_name
    }

    # Визначаємо, як відповідати
    reply_func = update.message.reply_text if update.message else update.callback_query.message.reply_text

    try:
        service = TicketsService()
        result = await service.create_thanks_ticket(
            telegram_id=update.effective_user.id,
            thanks_data=thanks_data
        )
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        await reply_func(
            text=result['message'],
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        logger.info(f"Thanks saved: {result.get('ticket_id')}")

    except Exception as e:
        logger.error(f"Error saving thanks: {e}")
        await reply_func("❌ Сталася помилка при збереженні подяки.")

    context.user_data.clear()
    return ConversationHandler.END