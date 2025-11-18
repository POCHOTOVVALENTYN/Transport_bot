from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config.messages import MESSAGES
from utils.logger import logger
from config.settings import MUSEUM_ADMIN_ID, GENERAL_ADMIN_IDS
from services.user_service import UserService

# Ініціалізація
user_service = UserService()


async def get_main_menu_keyboard(user_id: int):
    """Повертає клавіатуру головного меню з урахуванням прав доступу"""
    keyboard = [
        [InlineKeyboardButton("📍 Де мій транспорт? (Real-time)", callback_data="realtime_transport")],
        [InlineKeyboardButton("♿ Пошук інклюзивного транспорту", callback_data="accessible_start")],
        [InlineKeyboardButton("🎫 Квитки та тарифи", callback_data="tickets_menu")],
        [InlineKeyboardButton("✍️ Зворотній зв'язок", callback_data="feedback_menu")],
        [InlineKeyboardButton("ℹ️ Довідкова інформація", callback_data="info_menu")],
        [InlineKeyboardButton("👔 Вакансії", callback_data="vacancies_menu")],
        [InlineKeyboardButton("🎓 Навчально-курсовий комбінат", callback_data="education_menu")],
        [InlineKeyboardButton("🏛️ Музей КП 'ОМЕТ'", callback_data="museum_menu")],
        [InlineKeyboardButton("🏢 Про підприємство", callback_data="company_menu")],
    ]
    # 1. Якщо це Максим -> Додаємо кнопку Музею
    if user_id == MUSEUM_ADMIN_ID:
        keyboard.append(
            [InlineKeyboardButton("🏛️ Адмін-панель (Музей)", callback_data="admin_menu_show")]
        )

    # 2. Якщо це Ви або Тетяна -> Додаємо кнопку Загальної Адмінки
    if user_id in GENERAL_ADMIN_IDS:
        keyboard.append(
            [InlineKeyboardButton("📢 Адмін-панель (Новини/Стат)", callback_data="general_admin_menu")]
        )

    return InlineKeyboardMarkup(keyboard)


async def get_admin_main_menu_keyboard():
    """Повертає клавіатуру головного меню для Адміна Музею."""
    keyboard = [
        [InlineKeyboardButton("➕ Додати дату екскурсії", callback_data="admin_add_date")],
        [InlineKeyboardButton("➖ Видалити дату екскурсії", callback_data="admin_del_date_menu")],
        [InlineKeyboardButton("📋 Перелік зареєстрованих", callback_data="admin_show_bookings")],
        [InlineKeyboardButton("👤 Режим користувача", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    user_id = user.id
    logger.info(f"👤 User {user_id} started bot")

    # Реєструємо юзера в БД
    try:
        await user_service.register_user(user)
    except Exception as e:
        logger.error(f"User reg error: {e}")

    # Отримуємо правильну клавіатуру (функція сама визначить, які адмін-кнопки показати)
    keyboard = await get_main_menu_keyboard(user_id)

    await update.message.reply_text(
        MESSAGES['welcome'],
        reply_markup=keyboard
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    text = "🆘 Допомога:\n\n/start - Головне меню\n/help - Цей текст"
    await update.message.reply_text(text)