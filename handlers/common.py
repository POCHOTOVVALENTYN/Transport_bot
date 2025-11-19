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
    Видаляє будь-які повідомлення, що не є кнопками/командами.
    Захищає від спаму: попередження відображається лише 1 раз.
    """
    user_msg = update.message

    # Ігноруємо, якщо це не повідомлення користувача (наприклад, системне)
    if not user_msg:
        return

    # === 1. ЛОГІКА АНТИ-СПАМУ (ATOMІC CHECK) ===
    # Перевіряємо і ставимо прапорець МИТТЄВО, до будь-яких асинхронних дій (await).
    # Це запобігає "гонці", коли користувач шле 10 повідомлень за секунду.

    should_send_warning = False

    # Якщо прапорець вже стоїть - ми просто "тихий прибиральник"
    if not context.user_data.get('warning_active'):
        # Якщо прапорця немає - ми стаємо "головним", хто надішле попередження
        context.user_data['warning_active'] = True
        should_send_warning = True

        # ЛОГУВАННЯ
        user = update.effective_user
        logger.info(f"User {user.id} ({user.first_name}) triggered Anti-Spam cleaner.")

    # === 2. ВИДАЛЕННЯ ПОВІДОМЛЕННЯ ===
    # Видаляємо повідомлення користувача у будь-якому випадку
    try:
        await user_msg.delete()
    except Exception:
        pass

    # === 3. ВІДПРАВКА ПОПЕРЕДЖЕННЯ ===
    # Якщо ми не "головний" (should_send_warning == False), то просто виходимо.
    if not should_send_warning:
        return

    # Текст попередження
    warning_text = (
        "🧐 <b>Я Вас не розумію...</b>\n\n"
        "Будь ласка, користуйтеся <b>кнопками меню</b> для навігації.\n"
        "Я автоматично видаляю зайві повідомлення, щоб не засмічувати чат.\n\n"
        "<i>Це повідомлення зникне автоматично через 10 секунд... ⏳</i>"
    )

    try:
        # Надсилаємо попередження
        sent_warning = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=warning_text,
            parse_mode=ParseMode.HTML
        )

        # Чекаємо 10 секунд
        await asyncio.sleep(10)

        # Видаляємо попередження
        await sent_warning.delete()

    except Exception:
        pass
    finally:
        # === 4. ЗНІМАЄМО ПРАПОРЕЦЬ ===
        # Тільки після того, як попередження зникло, дозволяємо нове
        context.user_data['warning_active'] = False