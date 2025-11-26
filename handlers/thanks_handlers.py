import re
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode
from bot.states import States
from database.db import Database
from utils.logger import logger

db = Database()


# ============================================
# ПОМІЧНІ ФУНКЦІЇ
# ============================================

def generate_registration_number():
    """Генерує унікальний реєстраційний номер подяки"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    import random
    suffix = random.randint(1000, 9999)
    return f"THX-{timestamp}-{suffix}"


async def get_navigation_buttons(back_callback="feedback_menu"):
    """Повертає кнопки навігації для кожного кроку"""
    keyboard = [
        [InlineKeyboardButton("🚫 Скасувати", callback_data=back_callback)],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


def validate_name(name: str) -> bool:
    """Перевіряє П.І.Б. (мін 3 слова по 2+ символи кожне, лише літери)"""
    if len(name.strip()) < 5:
        return False
    # Дозволяємо кирилицю, дефіси, апострофи
    return bool(re.match(r"^[А-Яа-яЇїІіЄєҐґ\s'-]{5,}$", name))


def validate_board_number(board: str) -> bool:
    """Перевіряє бортовий номер (4 цифри)"""
    cleaned = board.strip()
    return bool(re.match(r"^\d{4}$", cleaned))


def validate_email(email: str) -> bool:
    """Перевіряє email"""
    return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email.strip()))


def validate_message(message: str) -> bool:
    """Перевіряє, чи повідомлення не спам (мін 10 символів, без GIF/стікерів)"""
    if len(message.strip()) < 10:
        return False
    # Перевіряємо, що це текст, а не GIF/смайлики
    return not any(char in message for char in ['🎬', '📹', '🎞️'])


# ============================================
# ОСНОВНІ ХЕНДЛЕРИ
# ============================================

async def thanks_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    КРОК 1: Користувач нажимає "Висловити подяку"
    Показуємо 2 кнопки: Конкретна чи Загальна
    """
    query = update.callback_query
    await query.answer()

    text = (
        "🙏 <b>Дякуємо, що вирішили залишити подяку!</b>\n\n"
        "Ваша подяка стосується конкретного водія/маршруту чи це загальна подяка?"
    )

    keyboard = [
        [InlineKeyboardButton("✍️ Написати конкретну подяку", callback_data="thanks:specific")],
        [InlineKeyboardButton("📝 Написати загальну подяку", callback_data="thanks:general")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return States.THANKS_CHOOSE_TYPE


# ============================================
# ГІЛКА 1: КОНКРЕТНА ПОДЯКА
# ============================================

async def thanks_specific_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    КРОК 2 (КОНКРЕТНА): Вибір типу транспорту
    """
    query = update.callback_query
    await query.answer()

    context.user_data['thanks_type'] = 'specific'

    text = (
        "🚊 <b>Оберіть тип транспорту</b>\n\n"
        "За яким транспортом вдячні?"
    )

    keyboard = [
        [InlineKeyboardButton("🚊 Трамвай", callback_data="thanks:transport:tram")],
        [InlineKeyboardButton("🚌 Тролейбус", callback_data="thanks:transport:trolleybus")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return States.THANKS_SPECIFIC_CHOOSE_TRANSPORT


async def thanks_transport_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    КРОК 3 (КОНКРЕТНА): Отримання типу транспорту, запит бортового номера
    """
    query = update.callback_query
    await query.answer()

    transport = query.data.split(":")[2]  # "tram" або "trolleybus"
    context.user_data['transport_type'] = transport

    text = (
        f"✅ <b>Обрано: {'Трамвай 🚊' if transport == 'tram' else 'Тролейбус 🚌'}</b>\n\n"
        "Вкажіть <b>бортовий номер</b> (4 цифри, напр: 1234).\n"
        "Якщо не пам'ятаєте — можна пропустити."
    )

    nav_buttons = await get_navigation_buttons()
    keyboard = [
        [InlineKeyboardButton("⏭️ Пропустити", callback_data="thanks:skip_board")]
    ]
    keyboard.append([nav_buttons.inline_keyboard[0][0], nav_buttons.inline_keyboard[1][0]])

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

    # Переходимо в стан очікування бортового номера (текст користувача)
    return States.THANKS_SPECIFIC_BOARD_NUMBER


async def thanks_board_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    КРОК 4 (КОНКРЕТНА): Отримання бортового номера та валідація
    """
    await update.message.delete()
    board_text = update.message.text.strip()

    # Валідація
    if not validate_board_number(board_text):
        await update.message.reply_text(
            "❌ <b>Помилка!</b> Бортовий номер повинен бути 4 цифри (напр: 1234).\n\n"
            "Спробуйте ще раз:",
            parse_mode=ParseMode.HTML
        )
        return States.THANKS_SPECIFIC_BOARD_NUMBER

    context.user_data['board_number'] = board_text
    logger.info(f"Specific thanks board: {board_text}")

    # Переходимо до запиту про причину подяки
    return await _ask_specific_reason(update, context)


async def thanks_skip_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """КРОК 4 (КОНКРЕТНА): Пропуск бортового номера"""
    query = update.callback_query
    await query.answer()

    context.user_data['board_number'] = None  # Не знають номера

    text = (
        "⏭️ <b>Збережено!</b>\n\n"
        "Тепер розкажіть, <b>за що саме вдячні?</b>\n"
        "(напр: За ввічливість водія, за чистоту у салоні)\n\n"
        "Якщо це стосується конкретного <b>водія чи кондуктора</b> — вкажіть його П.І.Б."
    )

    nav_buttons = await get_navigation_buttons()
    await query.edit_message_text(
        text=text,
        reply_markup=nav_buttons,
        parse_mode=ParseMode.HTML
    )

    return States.THANKS_SPECIFIC_REASON


async def _ask_specific_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    КРОК 5 (КОНКРЕТНА): Запит про причину подяки та ПІБ
    """
    text = (
        "📝 <b>Розкажіть, за що вдячні?</b>\n\n"
        "(напр: За ввічливість водія, за чистоту в салоні)\n\n"
        "Якщо це стосується конкретного <b>водія чи кондуктора</b> — вкажіть його П.І.Б."
    )

    nav_buttons = await get_navigation_buttons()
    await update.message.reply_text(
        text=text,
        reply_markup=nav_buttons,
        parse_mode=ParseMode.HTML
    )

    return States.THANKS_SPECIFIC_REASON


async def thanks_reason_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    КРОК 6 (КОНКРЕТНА): Отримання причини подяки + ПІБ водія
    """
    await update.message.delete()
    reason_text = update.message.text.strip()

    # Валідація
    if len(reason_text) < 10:
        await update.message.reply_text(
            "❌ <b>Помилка!</b> Опишіть детальніше (мінімум 10 символів).",
            parse_mode=ParseMode.HTML
        )
        return States.THANKS_SPECIFIC_REASON

    context.user_data['reason'] = reason_text
    logger.info(f"Specific thanks reason: {reason_text[:50]}")

    # Переходимо до запиту email
    text = "✉️ <b>Тепер вкажіть свою електронну пошту</b> для отримання звіту про розглядання подяки.\n\n(напр: user@gmail.com)"

    nav_buttons = await get_navigation_buttons()
    await update.message.reply_text(
        text=text,
        reply_markup=nav_buttons,
        parse_mode=ParseMode.HTML
    )

    return States.THANKS_SPECIFIC_EMAIL


async def thanks_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    КРОК 7 (КОНКРЕТНА): Отримання email та збереження подяки
    """
    await update.message.delete()
    email = update.message.text.strip()

    # Валідація email
    if not validate_email(email):
        await update.message.reply_text(
            "❌ <b>Помилка!</b> Невірна формат email (напр: user@gmail.com).",
            parse_mode=ParseMode.HTML
        )
        return States.THANKS_SPECIFIC_EMAIL

    context.user_data['email'] = email

    # Генеруємо реєстраційний номер
    reg_number = generate_registration_number()

    # Збереження в БД
    data = {
        'thanks_type': 'specific',
        'transport_type': context.user_data.get('transport_type'),
        'board_number': context.user_data.get('board_number'),
        'reason': context.user_data.get('reason'),
        'email': email,
        'user_id': update.effective_user.id,
        'username': update.effective_user.username,
        'category': 'Подяки'
    }

    try:
        ticket_id = await db.create_feedback(data)

        success_text = (
            f"✅ <b>Подяка зареєстрована!</b>\n\n"
            f"🆔 <b>Номер звернення:</b> <code>{reg_number}</code>\n\n"
            f"📧 Усі деталі надіслані на вашу пошту: <code>{email}</code>\n\n"
            f"🙏 Дякуємо за Вашу підтримку! Ми передамо цю подяку екіпажу."
        )

        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]

        await update.message.reply_text(
            text=success_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

        logger.info(f"Specific thanks saved: {ticket_id}")

    except Exception as e:
        logger.error(f"Error saving specific thanks: {e}")
        await update.message.reply_text("❌ Сталася помилка при збереженні. Спробуйте пізніше.")

    context.user_data.clear()
    return ConversationHandler.END


# ============================================
# ГІЛКА 2: ЗАГАЛЬНА ПОДЯКА
# ============================================

async def thanks_general_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    КРОК 2 (ЗАГАЛЬНА): Запит про суть вдячності
    """
    query = update.callback_query
    await query.answer()

    context.user_data['thanks_type'] = 'general'

    text = (
        "📝 <b>Розкажіть про Вашу вдячність</b>\n\n"
        "Опишіть, за що Ви вдячні КП 'ОМЕТ'.\n\n"
        "⚠️ <b>Важливо:</b> Напишіть детально (мінімум 15 символів), "
        "без спама, GIF чи стікерів."
    )

    nav_buttons = await get_navigation_buttons()
    await query.edit_message_text(
        text=text,
        reply_markup=nav_buttons,
        parse_mode=ParseMode.HTML
    )

    return States.THANKS_GENERAL_MESSAGE


async def thanks_general_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    КРОК 3 (ЗАГАЛЬНА): Отримання тексту подяки та валідація
    """
    await update.message.delete()
    message = update.message.text.strip()

    # Валідація
    if not validate_message(message):
        await update.message.reply_text(
            "❌ <b>Помилка!</b>\n\n"
            "• Опис повинен мати мінімум 15 символів\n"
            "• Без спама, GIF, стікерів\n\n"
            "Спробуйте ще раз:",
            parse_mode=ParseMode.HTML
        )
        return States.THANKS_GENERAL_MESSAGE

    context.user_data['message'] = message
    logger.info(f"General thanks message: {message[:50]}")

    # Запит П.І.Б.
    text = "👤 <b>Вкажіть Ваше П.І.Б.</b>\n\n(напр: Петренко Іван Сергійович)"

    nav_buttons = await get_navigation_buttons()
    await update.message.reply_text(
        text=text,
        reply_markup=nav_buttons,
        parse_mode=ParseMode.HTML
    )

    return States.THANKS_GENERAL_NAME


async def thanks_general_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    КРОК 4 (ЗАГАЛЬНА): Отримання П.І.Б. та валідація
    """
    await update.message.delete()
    name = update.message.text.strip()

    # Валідація
    if not validate_name(name):
        await update.message.reply_text(
            "❌ <b>Помилка!</b>\n\n"
            "П.І.Б. повинно мати:\n"
            "• Мінімум 5 символів\n"
            "• Тільки літери, дефіси, апострофи\n\n"
            "Спробуйте ще раз (напр: Петренко Іван Сергійович):",
            parse_mode=ParseMode.HTML
        )
        return States.THANKS_GENERAL_NAME

    context.user_data['user_name'] = name
    logger.info(f"General thanks name: {name}")

    # Запит email
    text = "✉️ <b>Вкажіть свою електронну пошту</b>\n\n(напр: user@gmail.com)"

    nav_buttons = await get_navigation_buttons()
    await update.message.reply_text(
        text=text,
        reply_markup=nav_buttons,
        parse_mode=ParseMode.HTML
    )

    return States.THANKS_GENERAL_EMAIL


async def thanks_general_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    КРОК 5 (ЗАГАЛЬНА): Отримання email та збереження
    """
    await update.message.delete()
    email = update.message.text.strip()

    # Валідація
    if not validate_email(email):
        await update.message.reply_text(
            "❌ <b>Помилка!</b> Невірний формат email (напр: user@gmail.com).",
            parse_mode=ParseMode.HTML
        )
        return States.THANKS_GENERAL_EMAIL

    context.user_data['email'] = email

    # Генеруємо реєстраційний номер
    reg_number = generate_registration_number()

    # Збереження в БД
    data = {
        'thanks_type': 'general',
        'text': context.user_data.get('message'),
        'user_name': context.user_data.get('user_name'),
        'email': email,
        'user_id': update.effective_user.id,
        'username': update.effective_user.username,
        'category': 'Подяки'
    }

    try:
        ticket_id = await db.create_feedback(data)

        success_text = (
            f"✅ <b>Подяка зареєстрована!</b>\n\n"
            f"🆔 <b>Номер звернення:</b> <code>{reg_number}</code>\n\n"
            f"📧 Усі деталі надіслані на вашу пошту: <code>{email}</code>\n\n"
            f"🙏 Дякуємо за Вашу підтримку! Ми обов'язково розглянемо Вашу подяку."
        )

        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]

        await update.message.reply_text(
            text=success_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

        logger.info(f"General thanks saved: {ticket_id}")

    except Exception as e:
        logger.error(f"Error saving general thanks: {e}")
        await update.message.reply_text("❌ Сталася помилка при збереженні. Спробуйте пізніше.")

    context.user_data.clear()
    return ConversationHandler.END


# ============================================
# УТИЛІТИ (Скасування)
# ============================================

async def thanks_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скасування процесу подяки"""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "❌ <b>Творення подяки скасовано.</b>\n\n"
            "Повертаємо Вас в меню...",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            "❌ <b>Творення подяки скасовано.</b>"
        )

    context.user_data.clear()

    # Повертаємо в меню зворотнього зв'язку
    from handlers.menu_handlers import main_menu
    return await main_menu(update, context)


# ============================================
# РЕЄСТРАЦІЯ ВСІХ ХЕНДЛЕРІВ (Викликається з bot.py)
# ============================================

def register_thanks_handlers():
    """
    Фабрика для реєстрації всіх хендлерів подяк.
    Викликається з bot.py при налаштуванні ConversationHandler.
    """
    return {
        'entry_points': [
            ('callback', 'thanks', thanks_start)
        ],
        'states': {
            States.THANKS_CHOOSE_TYPE: [
                ('callback', 'thanks:specific', thanks_specific_type_selection),
                ('callback', 'thanks:general', thanks_general_start),
            ],
            States.THANKS_SPECIFIC_CHOOSE_TRANSPORT: [
                ('callback', 'thanks:transport:', thanks_transport_selected),
            ],
            States.THANKS_SPECIFIC_BOARD_NUMBER: [
                ('message', None, thanks_board_number_input),
                ('callback', 'thanks:skip_board', thanks_skip_board),
            ],
            States.THANKS_SPECIFIC_REASON: [
                ('message', None, thanks_reason_input),
            ],
            States.THANKS_SPECIFIC_EMAIL: [
                ('message', None, thanks_email_input),
            ],
            States.THANKS_GENERAL_MESSAGE: [
                ('message', None, thanks_general_message),
            ],
            States.THANKS_GENERAL_NAME: [
                ('message', None, thanks_general_name),
            ],
            States.THANKS_GENERAL_EMAIL: [
                ('message', None, thanks_general_email),
            ]
        }
    }