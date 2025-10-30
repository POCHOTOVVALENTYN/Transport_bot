# handlers/museum_handlers.py
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from config.messages import MESSAGES
from handlers.common import get_back_keyboard
from bot.states import States
from utils.logger import logger


async def show_museum_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує меню 'Музей'."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🖼️ Інфо про музей", callback_data="museum:info")],
        [InlineKeyboardButton("📱 Соц. мережі музею", callback_data="museum:socials")],
        [InlineKeyboardButton("🗓️ Запис на екскурсію", callback_data="museum:register_start")],
        [InlineKeyboardButton("⬅️ Головне меню", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        text="🏛️ Розділ 'Музей КП 'ОМЕТ''. Оберіть опцію:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_museum_static(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє статичні під-меню 'Музей'."""
    query = update.callback_query
    await query.answer()

    key = query.data.split(":")[1]
    text = MESSAGES.get(f"museum_{key}", "Інформація не знайдена.")

    keyboard = await get_back_keyboard("museum_menu")
    await query.edit_message_text(text=text, reply_markup=keyboard, disable_web_page_preview=True)


# --- ConversationHandler для реєстрації ---

async def museum_register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок реєстрації до музею."""
    query = update.callback_query
    await query.answer()

    # Тут може бути логіка перевірки дати
    nearest_date = "25.11.2025"

    keyboard = [
        [
            InlineKeyboardButton("✅ Так, влаштовує", callback_data=f"museum_date:{nearest_date}"),
            InlineKeyboardButton("📅 Обрати іншу", callback_data="museum_date:other")
        ],
        [InlineKeyboardButton("⬅️ Скасувати", callback_data="museum_menu")]
    ]

    await query.edit_message_text(
        text=f"Найближча вільна дата для групової екскурсії: {nearest_date}. Вас влаштовує?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return States.MUSEUM_DATE


async def museum_get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує дату (зараз заглушка)."""
    query = update.callback_query
    await query.answer()

    if "other" in query.data:
        await query.edit_message_text(
            text="Для вибору іншої дати, будь ласка, зателефонуйте організатору: 050-399-42-11",
            reply_markup=await get_back_keyboard("museum_menu")
        )
        return ConversationHandler.END

    context.user_data['museum_date'] = query.data.split(":")[1]
    await query.edit_message_text("Вкажіть кількість осіб у вашій групі (напишіть цифрою):")
    return States.MUSEUM_PEOPLE_COUNT


async def museum_get_people_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує кількість осіб."""
    try:
        count = int(update.message.text)
    except ValueError:
        await update.message.reply_text("Будь ласка, введіть число. Скільки осіб?")
        return States.MUSEUM_PEOPLE_COUNT

    if count == 1:
        await update.message.reply_text(
            "На жаль, екскурсії проводяться для груп від 2-х осіб. "
            "Будь ласка, зателефонуйте 050-399-42-11, можливо, ми зможемо додати вас до вже існуючої групи.",
            reply_markup=await get_back_keyboard("museum_menu")
        )
        return ConversationHandler.END

    if count > 10:
        await update.message.reply_text(
            "Для груп понад 10 осіб потрібна індивідуальна домовленість. "
            "Будь ласка, зателефонуйте організатору за номером 050-399-42-11.",
            reply_markup=await get_back_keyboard("museum_menu")
        )
        return ConversationHandler.END

    context.user_data['museum_people_count'] = count
    await update.message.reply_text("Чудово! Вкажіть Ваші ПІБ та контактний телефон для підтвердження реєстрації.")
    return States.MUSEUM_CONTACT_INFO


async def museum_save_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Зберігає реєстрацію."""
    contact_info = update.message.text

    # Тут логіка збереження (напр., в Google Sheets або відправка адміну)
    logger.info(f"New museum registration: {context.user_data['museum_date']}, "
                f"{context.user_data['museum_people_count']} people, contact: {contact_info}")

    await update.message.reply_text(
        "✅ Дякуємо! Ваша заявка прийнята. Організатор зв'яжеться з вами для підтвердження.",
        reply_markup=await get_back_keyboard("main_menu")
    )
    context.user_data.clear()
    return ConversationHandler.END