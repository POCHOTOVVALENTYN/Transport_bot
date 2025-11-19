import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from handlers.command_handlers import get_main_menu_keyboard
from utils.logger import logger  # Додати імпорт нагорі


async def dismiss_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Видаляє повідомлення розсилки і показує Головне меню.
    """
    query = update.callback_query
    await query.answer()

    # 1. Видаляємо повідомлення з новиною
    try:
        await query.message.delete()
    except Exception:
        pass

    # 2. Викликаємо головне меню (щоб користувач повернувся в інтерфейс)
    from handlers.menu_handlers import main_menu
    await main_menu(update, context)


async def get_back_keyboard(callback_data: str = "main_menu") -> InlineKeyboardMarkup:
    """Повертає клавіатуру з кнопками навігації."""
    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data=callback_data)],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def get_back_button_only(callback_data: str = "main_menu") -> InlineKeyboardMarkup:
    """Повертає клавіатуру тільки з кнопкою 'Назад'."""
    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data=callback_data)]
    ]
    return InlineKeyboardMarkup(keyboard)


async def get_cancel_keyboard(cancel_callback: str = "museum_menu") -> InlineKeyboardMarkup:
    """
    Повертає клавіатуру для скасування поточного діалогу.
    'cancel_callback' - це куди поверне кнопка "Скасувати" (за замовчуванням - меню музею).
    """
    keyboard = [
        [InlineKeyboardButton("🚫 Скасувати реєстрацію", callback_data=cancel_callback)],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def get_feedback_cancel_keyboard(cancel_callback: str = "feedback_menu") -> InlineKeyboardMarkup:
    """
    Повертає клавіатуру для скасування діалогів зворотнього зв'язку.
    """
    keyboard = [
        [InlineKeyboardButton("🚫 Скасувати", callback_data=cancel_callback)],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def handle_unexpected_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Глобальний 'чистильник'.
    Працює миттєво: видаляє спам і запускає фонову задачу для попередження.
    """
    user_msg = update.message
    if not user_msg:
        return

    # 1. Миттєво видаляємо повідомлення користувача
    try:
        await user_msg.delete()
    except Exception:
        pass

    # 2. Перевіряємо прапорець (чи вже активне попередження?)
    if context.user_data.get('warning_active'):
        # Якщо попередження вже висить - просто виходимо.
        # Ми вже видалили повідомлення вище, більше нічого робити не треба.
        return

    # 3. Якщо прапорця немає - ставимо його і надсилаємо попередження
    context.user_data['warning_active'] = True

    # Логування (опціонально)
    user = update.effective_user
    logger.info(f"User {user.id} triggered Anti-Spam.")

    warning_text = (
        "🧐 <b>Я Вас не розумію...</b>\n\n"
        "Будь ласка, користуйтеся <b>кнопками меню</b> для навігації.\n"
        "Я автоматично видаляю зайві повідомлення, щоб не засмічувати чат.\n\n"
        "<i>Це повідомлення зникне автоматично через 5 секунд... ⏳</i>"
    )

    try:
        sent_warning = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=warning_text,
            parse_mode=ParseMode.HTML
        )

        # 4. ГОЛОВНА ЗМІНА: Запускаємо очікування у ФОНІ ("Fire-and-Forget")
        # Ми не використовуємо 'await', тому бот не блокується і одразу переходить до наступного повідомлення.
        asyncio.create_task(cleanup_warning_task(context, sent_warning.message_id, update.effective_chat.id))

    except Exception:
        # Якщо не вдалося надіслати (наприклад, бан), знімаємо прапорець одразу
        context.user_data['warning_active'] = False


async def cleanup_warning_task(context, message_id, chat_id):
    """
    Ця функція працює у фоновому режимі паралельно з основним ботом.
    Вона чекає 10 секунд, видаляє попередження і знімає блокування.
    """
    await asyncio.sleep(5)  # Чекаємо тут, нікому не заважаючи

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass  # Повідомлення могло бути видалене вручну
    finally:
        # Знімаємо прапорець - тепер можна надсилати нове попередження
        context.user_data['warning_active'] = False