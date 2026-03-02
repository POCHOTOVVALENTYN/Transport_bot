# handlers/subscription_handlers.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from services.user_service import UserService
from handlers.command_handlers import get_main_menu_keyboard  # Імпорт для повернення в меню

user_service = UserService()


async def show_subscription_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запитує у користувача згоду на сповіщення"""
    query = update.callback_query
    await query.answer()

    text = (
        "🔔 <b>Налаштування сповіщень</b>\n\n"
        "Чи бажаєте Ви отримувати важливі повідомлення про:\n"
        "🚋 Зміни в роботі транспорту\n"
        "🗞 Актуальні новини КП «ОМЕТ»\n"
        "🚨 Екстрені ситуації\n\n"
        "<i>Ми не надсилаємо спам, лише важливу інформацію!</i>"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Так, я згоден", callback_data="sub:yes")],
        [InlineKeyboardButton("🔕 Ні, не потрібно", callback_data="sub:no")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )


async def handle_subscription_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє вибір Так/Ні"""
    query = update.callback_query
    await query.answer()

    choice = query.data.split(":")[1]  # "yes" або "no"
    user_id = update.effective_user.id

    if choice == "yes":
        await user_service.set_subscription(user_id, True)
        text = (
            "🎉 <b>Дякуємо за Ваш вибір!</b>\n\n"
            "Надалі Ви будете отримувати повідомлення з актуальними новинами. "
            "Ви завжди будете в курсі подій! 🚀"
        )
    else:
        await user_service.set_subscription(user_id, False)
        text = (
            "👌 <b>Ваш вибір прийнято!</b>\n\n"
            "Ви відмовилися від розсилки новин. "
            "Якщо передумаєте — завжди можна змінити це в меню."
        )

    # Повертаємо в головне меню з новим текстом
    main_keyboard = await get_main_menu_keyboard(user_id)

    # Показуємо результат БЕЗ «порожнього» екрану:
    # спочатку пробуємо відредагувати поточне повідомлення,
    # а якщо не виходить — надсилаємо нове і лише потім видаляємо старе.
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=main_keyboard,
            parse_mode=ParseMode.HTML
        )
    except Exception:
        sent = await query.message.reply_text(
            text=text,
            reply_markup=main_keyboard,
            parse_mode=ParseMode.HTML
        )
        try:
            await query.message.delete()
        except Exception:
            pass