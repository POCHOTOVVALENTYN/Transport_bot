# handlers/company_handlers.py
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from config.messages import MESSAGES
from handlers.common import get_back_keyboard


async def show_company_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує меню 'Про підприємство'."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("👔 Вакансії", callback_data="company:vacancies")],
        [InlineKeyboardButton("🎓 Учбово-курсовий комбінат", callback_data="company:education")],
        [InlineKeyboardButton("🚌 Оренда та послуги", callback_data="company:services")],
        [InlineKeyboardButton("📰 Новини / Соц. мережі", callback_data="company:socials")],
        [InlineKeyboardButton("⬅️ Головне меню", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        text="🏢 Розділ 'Про підприємство'. Оберіть опцію:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_company_static(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє статичні під-меню 'Про підприємство'."""
    query = update.callback_query
    await query.answer()

    key = query.data.split(":")[1]
    text = MESSAGES.get(f"company_{key}", "Інформація не знайдена.")

    keyboard = await get_back_keyboard("company_menu")
    await query.edit_message_text(text=text, reply_markup=keyboard)


async def show_vacancies_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує під-меню 'Вакансії'."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("👷 З досвідом", callback_data="vacancy_type:experienced")],
        [InlineKeyboardButton("🧑‍🎓 Без досвіду (навчання)", callback_data="vacancy_type:trainee")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="company_menu")]
    ]

    await query.edit_message_text(
        text="👔 Оберіть категорію вакансій:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_vacancy_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує список вакансій (приклад)."""
    query = update.callback_query
    await query.answer()

    v_type = query.data.split(":")[1]
    keyboard = []

    if v_type == "experienced":
        keyboard = [
            [InlineKeyboardButton("Водій трамвая", callback_data="vacancy:tram_driver")],
            [InlineKeyboardButton("Слюсар-електрик", callback_data="vacancy:electrician")],
            [InlineKeyboardButton("Бухгалтер", callback_data="vacancy:accountant")],
        ]
    elif v_type == "trainee":
        keyboard = [
            [InlineKeyboardButton("Учень водія трамвая", callback_data="vacancy:tram_trainee")],
            [InlineKeyboardButton("Кондуктор", callback_data="vacancy:conductor")],
        ]

    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="company:vacancies")])

    await query.edit_message_text(
        text="Оберіть вакансію:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_vacancy_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує деталі вакансії."""
    query = update.callback_query
    await query.answer()

    key = query.data.split(":")[1]
    text = MESSAGES.get(f"vacancy_{key}", "Детальний опис вакансії не знайдено.")

    keyboard = await get_back_keyboard("company:vacancies")  # Повертаємо до вибору типу вакансій
    await query.edit_message_text(text=text, reply_markup=keyboard)