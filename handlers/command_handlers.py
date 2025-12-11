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
        [InlineKeyboardButton("♿ Пошук низькопідлогового транспорту", callback_data="accessible_start")],
        [InlineKeyboardButton("🎫 Квитки та тарифи", callback_data="tickets_menu")],
        [InlineKeyboardButton("✍️ Звернення та пропозиції", callback_data="feedback_menu")],
        [InlineKeyboardButton("ℹ️ Довідкова інформація", callback_data="info_menu")],
        [InlineKeyboardButton("👔 Вакансії", callback_data="vacancies_menu")],
        [InlineKeyboardButton("🎓 Учбово-курсовий комбінат", callback_data="education_menu")],
        [InlineKeyboardButton("🏛️ Музей КП 'ОМЕТ'", callback_data="museum_menu")],
        [InlineKeyboardButton("🏢 Про підприємство", callback_data="company_menu")],
        [InlineKeyboardButton("🔔 Сповіщення від бота", callback_data="subscription_menu")]
    ]
    # 1. Якщо це Максим -> Додаємо кнопку Музею
    if user_id == MUSEUM_ADMIN_ID:
        keyboard.append([InlineKeyboardButton("🏛️ Адмін-панель (Музей)", callback_data="admin_museum_menu")])

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
    """
    Обробка команди /start.
    Вітає користувача, показує головне меню та видаляє команду /start з чату.
    """
    user = update.effective_user
    user_id = user.id
    logger.info(f"👤 User {user_id} started bot")

    # 1. Видалення команди /start (Чистий чат)
    if update.message:
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Не вдалося видалити повідомлення /start для {user.id}: {e}")

    # 2. Реєструємо юзера в БД
    try:
        await user_service.register_user(user)
    except Exception as e:
        logger.error(f"User reg error: {e}")

    # 3. Передаємо управління в main_menu
    # ВАЖЛИВО: Імпорт робимо тут, щоб уникнути циклічної помилки (Circular Import),
    # оскільки menu_handlers вже імпортує get_main_menu_keyboard з цього файлу.
    from handlers.menu_handlers import main_menu

    await main_menu(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    text = "🆘 Допомога:\n\n/start - Головне меню\n/help - Цей текст"
    # Для help теж бажано видаляти повідомлення користувача, якщо хочете ідеальної чистоти
    if update.message:
        try:
            await update.message.delete()
        except Exception:
            pass

    await update.message.reply_text(text)