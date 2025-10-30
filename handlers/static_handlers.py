from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.logger import logger


# Клавіатура "Назад"
async def get_back_button(callback_data="main_menu"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data=callback_data)]
    ])


async def realtime_transport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник для 'Де мій транспорт?'"""
    query = update.callback_query
    await query.answer()

    text = """
Для відстеження руху транспорту в реальному часі, будь ласка, скористайтеся офіційним партнерським додатком "MISTO".

Він показує точне місцезнаходження всіх трамваїв та тролейбусів на карті Одеси та дає прогноз прибуття на вашу зупинку.
    """

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Завантажити для iPhone (App Store)",
                              url="https://apps.apple.com/ua/app/misto/id6738929703")],
        [InlineKeyboardButton("➡️ Завантажити для Android (Google Play)",
                              url="https://play.google.com/store/apps/details?id=tech.misto.android.misto&hl=uk")],
        [InlineKeyboardButton("⬅️ Головне меню", callback_data="main_menu")]
    ])

    await query.edit_message_text(text=text, reply_markup=keyboard, disable_web_page_preview=True)


# ... (Тут ви можете додати функції для 5.1, 5.2, 5.3, 5.4, 4.4 тощо) ...

async def lost_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник для 'Загублені речі'"""
    query = update.callback_query
    await query.answer()

    text = """
Інформаційний центр знаходиться за адресою: [Адреса]. 
Телефон: [Телефон]. 
Години роботи: [Години].
    """
    keyboard = await get_back_button("feedback_menu")  # Повернення до меню "Зворотний зв'язок"
    await query.edit_message_text(text=text, reply_markup=keyboard)