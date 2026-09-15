from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes


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