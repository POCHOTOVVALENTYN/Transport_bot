import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from handlers.command_handlers import get_main_menu_keyboard


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


# handlers/common.py
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode


# ... інші імпорти ...

async def handle_unexpected_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Глобальний "чистильник".
    Видаляє будь-які повідомлення, що не є кнопками/командами.
    Захищає від спаму (відправляє лише 1 попередження на 10 секунд).
    """
    user_msg = update.message

    # Ігноруємо, якщо це не повідомлення користувача (наприклад, редагування)
    if not user_msg:
        return

    # 1. Миттєво видаляємо повідомлення порушника
    try:
        await user_msg.delete()
    except Exception:
        # Може виникнути, якщо повідомлення вже видалено або бот не має прав
        pass

    # 2. Перевірка "Анти-Спам": чи вже висить активне попередження?
    # Якщо так - просто виходимо (повідомлення ми вже видалили вище)
    if context.user_data.get('warning_active'):
        return

    # 3. Формуємо текст попередження
    warning_text = (
        "🧐 <b>Я Вас не розумію...</b>\n\n"
        "Будь ласка, користуйтеся <b>кнопками меню</b> для навігації.\n"
        "Я автоматично видаляю текстові повідомлення та файли, щоб не засмічувати чат.\n\n"
        "<i>Це повідомлення зникне автоматично через 10 секунд... ⏳</i>"
    )

    # 4. Надсилаємо попередження та ставимо "прапорець"
    try:
        # Ставимо прапорець ДО відправки, щоб уникнути гонки (race condition) при дуже швидкому спамі
        context.user_data['warning_active'] = True

        sent_warning = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=warning_text,
            parse_mode=ParseMode.HTML
        )

        # 5. Чекаємо 10 секунд (повідомлення висить)
        await asyncio.sleep(10)

        # 6. Видаляємо попередження
        await sent_warning.delete()

    except Exception:
        pass
    finally:
        # 7. Знімаємо прапорець (тепер можна надіслати нове попередження, якщо юзер знову напише)
        context.user_data['warning_active'] = False