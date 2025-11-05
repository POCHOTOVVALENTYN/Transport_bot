from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from utils.logger import logger
from handlers.common import get_back_keyboard


async def realtime_transport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник для 'Де мій транспорт?'"""
    query = update.callback_query
    await query.answer()

    text = """
📍 Для відстеження руху транспорту в реальному часі, будь ласка, скористайтеся офіційним партнерським додатком "MISTO".

Він показує точне місцезнаходження всіх трамваїв та тролейбусів на карті Одеси та дає прогноз прибуття на вашу зупинку.
    """

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Завантажити для iPhone (App Store)",
                              url="https://apps.apple.com/ua/app/misto/id6738929703")],
        [InlineKeyboardButton("📱 Завантажити для Android (Google Play)",
                              url="https://play.google.com/store/apps/details?id=tech.misto.android.misto&hl=uk")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ])

    await query.edit_message_text(text=text, reply_markup=keyboard, disable_web_page_preview=True)


async def lost_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник для 'Загублені речі'"""
    query = update.callback_query
    await query.answer()

    text = """
🔍 <b>Загубили речі в нашому транспорті?</b>

Забрати загублені речі можна у <b>Інформаційному центрі</b> КП "ОМЕТ".

📍 <b>Адреса:</b>
м. Одеса, вул. Водопровідна, 1

📞 <b>Телефон:</b>
<code>048-717-54-54</code>

🗓️ <b>Графік роботи:</b>
Пн - Нд, з 8:00 до 20:00
    """

    keyboard = await get_back_keyboard("feedback_menu")

    await query.edit_message_text(
        text=text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML # <-- Додаємо HTML для <b> та <code>
    )