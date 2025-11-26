from telegram import Update, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from bot.states import States
from config.messages import MESSAGES
from database.db import Database
from services.user_service import UserService
from utils.logger import logger
from utils.text_formatter import format_feedback_message

# Ініціалізація сервісів
db = Database()
user_service = UserService()


async def thanks_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок сценарію подяки."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        text="🙏 <b>Дякуємо, що вирішили залишити відгук!</b>\n\n"
             "Напишіть текст вашої подяки. Це може бути опис ситуації, номер транспорту або ім'я водія.",
        parse_mode='HTML'
    )
    return States.THANKS_TEXT


async def thanks_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання тексту подяки."""
    text = update.message.text
    context.user_data['thanks_text'] = text
    logger.info(f"Thanks text: {text}")

    keyboard = [
        [InlineKeyboardButton("Не знаю / Пропустити", callback_data="skip_route")]
    ]
    # Додамо кнопки популярних маршрутів, якщо потрібно, або просто просимо ввести
    await update.message.reply_text(
        "Зазначте <b>номер маршруту</b> (наприклад: 7, 10, 145).\n"
        "Якщо не пам'ятаєте — натисніть кнопку нижче.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
    return States.THANKS_ROUTE


async def thanks_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання номеру маршруту."""
    route = update.message.text
    context.user_data['thanks_route'] = route
    logger.info(f"Thanks Route: {route}")

    await update.message.reply_text(
        "Вкажіть <b>бортовий номер</b> або держ. номер транспорту (якщо пам'ятаєте).\n"
        "Це допоможе нам знайти екіпаж.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Не знаю / Пропустити", callback_data="skip_board")]],
                                          one_time_keyboard=True),
        parse_mode='HTML'
    )
    return States.THANKS_BOARD


async def skip_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск кроку маршруту."""
    query = update.callback_query
    await query.answer()
    context.user_data['thanks_route'] = "Не вказано"

    await query.edit_message_text(
        text="Вкажіть <b>бортовий номер</b> або держ. номер транспорту (якщо пам'ятаєте).",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Не знаю / Пропустити", callback_data="skip_board")]],
                                          one_time_keyboard=True),
        parse_mode='HTML'
    )
    return States.THANKS_BOARD


async def thanks_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання бортового номеру."""
    board = update.message.text
    context.user_data['thanks_board'] = board
    logger.info(f"Thanks Board: {board}")
    return await _ask_contact(update, context)


async def skip_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск бортового номеру."""
    query = update.callback_query
    await query.answer()
    context.user_data['thanks_board'] = "Не вказано"
    # Оскільки це callback, треба відправити нове повідомлення або відредагувати старе
    # Але для логіки переходу простіше викликати спільну функцію, передавши query.message
    # Однак _ask_contact очікує update.message для reply_text.
    # Тому зробимо edit:

    await query.edit_message_text(
        text="Як до Вас звертатися? (Напишіть Ваше Ім'я)",
        parse_mode='HTML'
    )
    return States.THANKS_NAME


async def _ask_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Як до Вас звертатися? (Напишіть Ваше Ім'я)",
        parse_mode='HTML'
    )
    return States.THANKS_NAME


async def thanks_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фінал: збереження подяки."""
    name = update.message.text
    context.user_data['thanks_name'] = name
    user = update.effective_user
    logger.info(f"Thanks Name: {name}")

    # Збір даних
    data = {
        'type': 'thanks',  # ВАЖЛИВО: Тип подяка
        'text': context.user_data.get('thanks_text'),
        'route': context.user_data.get('thanks_route'),
        'board': context.user_data.get('thanks_board'),
        'name': name,
        'user_id': user.id,
        'username': user.username,
        'phone': "Не вказано",  # Для подяк телефон не обов'язковий
        'category': 'Подяки'  # <--- ВИПРАВЛЕННЯ: Явно вказуємо категорію "Подяки"
    }

    try:
        # Зберігаємо в БД
        # Метод add_complaint (або аналогічний в DB) повертає ID
        # Важливо переконатися, що метод create_feedback або аналогічний підтримує 'category'
        ticket_id = await db.create_feedback(data)

        logger.info(f"Thanks saved: {ticket_id}")

        await update.message.reply_text(
            f"✅ <b>Дякуємо! Ваша подяка зареєстрована.</b>\n\n"
            f"🆔 Номер звернення: <code>{ticket_id}</code>\n"
            f"Ми обов'язково передамо її екіпажу та керівництву! 🤝",
            parse_mode='HTML'
        )

        # Спроба відправити в Google Sheets (асинхронно або через чергу)
        # Тут ми покладаємось на те, що sync_service підхопить це пізніше,
        # або викликаємо user_service.sync_one_row(ticket_id)

    except Exception as e:
        logger.error(f"Error saving thanks: {e}", exc_info=True)
        await update.message.reply_text("❌ Сталася помилка при збереженні. Спробуйте пізніше.")

    from handlers.menu_handlers import main_menu
    return await main_menu(update, context)


async def thanks_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скасування."""
    await update.message.reply_text("❌ Створення подяки скасовано.")
    from handlers.menu_handlers import main_menu
    return await main_menu(update, context)