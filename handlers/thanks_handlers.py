import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from services.tickets_service import TicketsService
from bot.states import States
from utils.logger import logger
from handlers.common import get_feedback_cancel_keyboard  # <-- Використовуємо нову кнопку
#from config.settings import ROUTES

#ALL_ROUTES = set(str(r) for r in ROUTES["tram"] + ROUTES["trolleybus"])


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
    """Отримання та ВАЛІДАЦІЯ маршруту (з кешу EasyWay)."""
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

    # --- ПОЧАТОК ВИПРАВЛЕННЯ ---
    # 1. Отримуємо динамічну мапу маршрутів з кешу (який завантажується при старті)
    structured_map = context.bot_data.get('easyway_structured_map', {"tram": [], "trolleybus": []})

    # 2. Створюємо сет ІМЕН маршрутів (напр. "5", "7", "10A")
    tram_names = {r['name'] for r in structured_map.get("tram", [])}
    trolley_names = {r['name'] for r in structured_map.get("trolleybus", [])}
    all_route_names = tram_names.union(trolley_names)

    if not all_route_names:
        # Аварійний випадок, якщо EasyWay не завантажився
        logger.error("THANKS: 'easyway_structured_map' порожній. Валідація маршруту неможлива.")
        # Ми пропустимо валідацію, щоб не блокувати користувача

    # 3. Валідуємо по динамічному сету
    elif route_text not in all_route_names:
        sent_message = await update.message.reply_text(
            f"❌ Маршруту '<b>{route_text}</b>' не знайдено в базі EasyWay.\n\n"
            f"Будь ласка, введіть коректний номер (тільки цифри).",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        context.user_data['dialog_message_id'] = sent_message.message_id
        return States.THANKS_ROUTE
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

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
        [InlineKeyboardButton("🔘 Вказати своє П.І.Б.", callback_data="thanks_name:yes")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    text = "Дякуємо! Вкажіть також Ваші ідентифікаційні дані."

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
    """Зберігає подяку (тільки з ім'ям)."""

    await update.message.delete()
    name_text = update.message.text.strip()
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")  # Для помилки валідації

    try:
        # Видаляємо останнє запитання бота (про ПІБ)
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete final thanks messages: {e}")

    # --- ПОКРАЩЕННЯ: Додаємо валідацію ПІБ ---
    # (Раніше тут була логіка для "Анонім")
    if not re.match(r"^[А-Яа-яЇїІіЄєҐґA-Za-z\s'-]{5,}$", name_text):
        sent_message = await update.message.reply_text(
            f"❌ Будь ласка, введіть коректне ПІБ (тільки літери, довжина від 5 символів).",
            reply_markup=keyboard
        )
        context.user_data['dialog_message_id'] = sent_message.message_id
        return States.THANKS_GET_NAME  # Повертаємо на крок введення імені

    # Валідація пройдена
    user_name = name_text
    logger.info(f"Thanks Name: {user_name}")
    # --- КІНЕЦЬ ПОКРАЩЕННЯ ---

    # Збираємо дані
    thanks_data = {
        "text": context.user_data.get('thanks_text'),
        "route": context.user_data.get('thanks_route'),
        "board_number": context.user_data.get('thanks_board'),
        "user_name": user_name  # Тепер тут завжди буде ім'я
    }

    # Відповідь (тепер тільки від MessageHandler, 'elif update.callback_query' видалено)
    reply_func = update.message.reply_text

    try:
        service = TicketsService()
        result = await service.create_thanks_ticket(
            telegram_id=update.effective_user.id,
            thanks_data=thanks_data
        )
        keyboard_final = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        await reply_func(
            text=result['message'],
            reply_markup=InlineKeyboardMarkup(keyboard_final)
        )
        logger.info(f"Thanks saved: {result.get('ticket_id')}")

    except Exception as e:
        logger.error(f"Error saving thanks: {e}")
        await reply_func("❌ Сталася помилка при збереженні подяки.")

    context.user_data.clear()
    return ConversationHandler.END