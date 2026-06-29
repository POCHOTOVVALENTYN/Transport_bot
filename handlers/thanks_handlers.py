import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode
from bot.states import States
from database.db import Database
from utils.logger import logger
from handlers.common import safe_edit_prev_message

# Імпортуємо clean_phone з complaint_handlers
from handlers.complaint_handlers import clean_phone

db = Database()


# === ДОПОМІЖНІ ФУНКЦІЇ ===

def generate_registration_number():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    import random
    suffix = random.randint(1000, 9999)
    return f"THX-{timestamp}-{suffix}"


async def get_navigation_buttons(back_callback="feedback_menu"):
    keyboard = [
        [InlineKeyboardButton("🚫 Скасувати", callback_data=back_callback)],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


# --- Валідатори ---
def validate_name(name: str) -> bool:
    return len(name.strip()) >= 5 and bool(re.match(r"^[А-Яа-яЇїІіЄєҐґA-Za-z\s'-]+$", name))


def validate_board_number(board: str) -> bool:
    return bool(re.match(r"^\d{4}$", board.strip()))


def validate_email(email: str) -> bool:
    return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email.strip()))


def validate_message(message: str) -> bool:
    return len(message.strip()) >= 10


# ============================================
# ПОЧАТОК ДІАЛОГУ
# ============================================

async def thanks_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Очищення старих даних
    context.user_data.pop('thanks_type', None)
    context.user_data.pop('transport_type', None)
    context.user_data.pop('board_number', None)
    context.user_data.pop('reason', None)
    context.user_data.pop('message', None)
    context.user_data.pop('user_name', None)
    context.user_data.pop('phone', None)
    context.user_data.pop('email', None)

    text = "🙏 <b>Дякуємо за відгук!</b>\n\nВаша подяка стосується конкретного транспорту чи загальна?"
    keyboard = [
        [InlineKeyboardButton("🚊 Конкретна (транспорт/водій)", callback_data="thanks:specific")],
        [InlineKeyboardButton("🏢 Загальна (підприємство)", callback_data="thanks:general")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    sent_msg = await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard),
                                             parse_mode=ParseMode.HTML)
    context.user_data['last_bot_msg_id'] = sent_msg.message_id
    return States.THANKS_CHOOSE_TYPE


# ============================================
# ГІЛКА 1: КОНКРЕТНА
# ============================================

async def thanks_specific_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['thanks_type'] = 'specific'

    text = "🚊 <b>Оберіть тип транспорту:</b>"
    keyboard = [
        [InlineKeyboardButton("🚊 Трамвай", callback_data="thanks:transport:tram")],
        [InlineKeyboardButton("🚌 Тролейбус", callback_data="thanks:transport:trolleybus")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ]

    sent_msg = await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard),
                                             parse_mode=ParseMode.HTML)
    context.user_data['last_bot_msg_id'] = sent_msg.message_id
    return States.THANKS_SPECIFIC_CHOOSE_TRANSPORT


async def thanks_transport_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    transport = query.data.split(":")[2]
    context.user_data['transport_type'] = transport

    text = (
        f"✅ <b>Обрано: {transport}</b>\n\n"
        "Введіть <b>бортовий номер</b> (4 цифри, напр: 4013).\n"
        "Якщо не знаєте — натисніть 'Пропустити'."
    )
    keyboard = [[InlineKeyboardButton("⏭️ Пропустити", callback_data="thanks:skip_board")]]
    keyboard.extend((await get_navigation_buttons()).inline_keyboard)

    sent_msg = await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard),
                                             parse_mode=ParseMode.HTML)
    context.user_data['last_bot_msg_id'] = sent_msg.message_id
    return States.THANKS_SPECIFIC_BOARD_NUMBER


async def thanks_board_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.delete()

    board = update.message.text.strip()
    if not validate_board_number(board):
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text="❌ Номер має бути з 4 цифр (напр: 7011). Спробуйте ще раз:",
            reply_markup=await get_navigation_buttons()
        )
        return States.THANKS_SPECIFIC_BOARD_NUMBER

    context.user_data['board_number'] = board
    return await _ask_specific_reason(update, context)


async def thanks_skip_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['board_number'] = "Не вказано"
    return await _ask_specific_reason(update, context, is_callback=True)


async def _ask_specific_reason(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback=False):
    text = "📝 <b>Напишіть текст подяки:</b>\n\n(За що вдячні? ПІБ водія, дата події тощо. Мінімум 10 символів):"
    markup = await get_navigation_buttons()

    if is_callback:
        msg = await update.callback_query.edit_message_text(text=text, reply_markup=markup, parse_mode=ParseMode.HTML)
        context.user_data['last_bot_msg_id'] = msg.message_id
    else:
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML
        )
    return States.THANKS_SPECIFIC_REASON


async def thanks_reason_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.delete()

    text = update.message.text.strip()
    if not validate_message(text):
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text="❌ Текст подяки надто короткий. Мінімум 10 символів. Спробуйте ще раз:",
            reply_markup=await get_navigation_buttons()
        )
        return States.THANKS_SPECIFIC_REASON

    context.user_data['reason'] = text

    # Запит телефону
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Пропустити ⏭️", callback_data="thanks:skip_phone")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ])
    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text="📞 <b>Введіть Ваш контактний номер телефону</b> (або пропустіть):",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return States.THANKS_SPECIFIC_PHONE


async def thanks_phone_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка вводу телефону (текст або кнопка пропуску)"""
    is_callback = update.callback_query is not None

    if is_callback:
        query = update.callback_query
        await query.answer()
        phone = "Не вказано"
    else:
        await update.message.delete()
        raw_phone = update.message.text.strip()
        phone = clean_phone(raw_phone)

        if not phone:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Пропустити ⏭️", callback_data="thanks:skip_phone")],
                [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
            ])
            await safe_edit_prev_message(
                context,
                update.effective_chat.id,
                text="⚠️ <b>Некоректний формат телефону!</b>\n\nВведіть ще раз (наприклад: 0951234567) або пропустіть:",
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
            # Залишаємося в поточному стані відповідно до типу
            thanks_type = context.user_data.get('thanks_type')
            return States.THANKS_SPECIFIC_PHONE if thanks_type == 'specific' else States.THANKS_GENERAL_PHONE

    context.user_data['phone'] = phone

    # Переходимо до Email
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Пропустити Email ⏭️", callback_data="thanks:skip_email")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ])
    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text="✉️ <b>Введіть Ваш Email</b> для зворотного зв'язку (або пропустіть):",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

    thanks_type = context.user_data.get('thanks_type')
    return States.THANKS_SPECIFIC_EMAIL if thanks_type == 'specific' else States.THANKS_GENERAL_EMAIL


# ============================================
# ГІЛКА 2: ЗАГАЛЬНА
# ============================================

async def thanks_general_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['thanks_type'] = 'general'
    msg = await query.edit_message_text("📝 <b>Напишіть текст подяки (мінімум 10 символів):</b>", reply_markup=await get_navigation_buttons(),
                                        parse_mode=ParseMode.HTML)
    context.user_data['last_bot_msg_id'] = msg.message_id
    return States.THANKS_GENERAL_MESSAGE


async def thanks_general_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.delete()
    text = update.message.text.strip()
    if not validate_message(text):
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text="❌ Мінімум 10 символів. Спробуйте ще раз:",
            reply_markup=await get_navigation_buttons()
        )
        return States.THANKS_GENERAL_MESSAGE
    context.user_data['message'] = text
    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text="👤 <b>Як до Вас звертатися? (П.І.Б., мінімум 5 символів):</b>",
        reply_markup=await get_navigation_buttons(),
        parse_mode=ParseMode.HTML
    )
    return States.THANKS_GENERAL_NAME


async def thanks_general_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.delete()
    name = update.message.text.strip()
    if not validate_name(name):
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text="❌ Вкажіть коректне П.І.Б. (лише літери, дефіс та апостроф, мінімум 5 символів):",
            reply_markup=await get_navigation_buttons()
        )
        return States.THANKS_GENERAL_NAME
    context.user_data['user_name'] = name

    # Запит телефону для Загальної подяки
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Пропустити ⏭️", callback_data="thanks:skip_phone")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ])
    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text="📞 <b>Введіть Ваш контактний номер телефону</b> (або пропустіть):",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return States.THANKS_GENERAL_PHONE


# ============================================
# ФІНАЛ: ПІДТВЕРДЖЕННЯ
# ============================================

async def thanks_input_email_and_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Цей хендлер ловить введення Email (останній крок або пропуск),
    та показує Summary.
    """
    is_callback = update.callback_query is not None

    if is_callback:
        query = update.callback_query
        await query.answer()
        email = "Не вказано"
    else:
        await update.message.delete()
        raw_email = update.message.text.strip()

        if not validate_email(raw_email):
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Пропустити Email ⏭️", callback_data="thanks:skip_email")],
                [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
            ])
            await safe_edit_prev_message(
                context,
                update.effective_chat.id,
                text="❌ Невірний формат Email. Спробуйте ще раз або пропустіть:",
                reply_markup=kb
            )
            # Повертаємось у той стан, з якого прийшли
            thanks_type = context.user_data.get('thanks_type')
            return States.THANKS_SPECIFIC_EMAIL if thanks_type == 'specific' else States.THANKS_GENERAL_EMAIL

        email = raw_email

    context.user_data['email'] = email

    # ФОРМУЄМО ЗВІТ ДЛЯ ПЕРЕВІРКИ
    thanks_type = context.user_data.get('thanks_type')
    phone = context.user_data.get('phone', 'Не вказано')

    if thanks_type == 'specific':
        summary = (
            f"🔍 <b>Перевірте Ваші дані:</b>\n\n"
            f"📌 <b>Тип:</b> Конкретне звернення ({context.user_data.get('transport_type')})\n"
            f"🔢 <b>Борт. номер:</b> {context.user_data.get('board_number')}\n"
            f"✍️ <b>Текст:</b> {context.user_data.get('reason')}\n"
            f"📞 <b>Телефон:</b> {phone}\n"
            f"📧 <b>Email:</b> {email}\n\n"
            "Все вірно?"
        )
    else:
        summary = (
            f"🔍 <b>Перевірте Ваші дані:</b>\n\n"
            f"📌 <b>Тип:</b> Загальне звернення\n"
            f"👤 <b>Ім'я:</b> {context.user_data.get('user_name')}\n"
            f"✍️ <b>Текст:</b> {context.user_data.get('message')}\n"
            f"📞 <b>Телефон:</b> {phone}\n"
            f"📧 <b>Email:</b> {email}\n\n"
            "Все вірно?"
        )

    # КНОПКИ ПІДТВЕРДЖЕННЯ
    keyboard = [
        [InlineKeyboardButton("✅ Все вірно, надіслати", callback_data="confirm_send")],
        [InlineKeyboardButton("🔄 Заповнити заново", callback_data="thanks"),
         InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ]

    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text=summary,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

    return States.THANKS_CONFIRMATION


async def thanks_confirm_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Кінцеве збереження у БД
    """
    query = update.callback_query
    await query.answer()

    reg_number = generate_registration_number()
    data = {
        'thanks_type': context.user_data.get('thanks_type'),
        'user_email': context.user_data.get('email', 'Не вказано'),
        'user_phone': context.user_data.get('phone', 'Не вказано'),
        'user_id': update.effective_user.id,
        'username': update.effective_user.username,
        'category': 'Подяки'
    }

    # Додаємо специфічні поля
    if data['thanks_type'] == 'specific':
        data.update({
            'transport_type': context.user_data.get('transport_type'),
            'board_number': context.user_data.get('board_number'),
            'text': context.user_data.get('reason'),
            'route': "N/A"
        })
    else:
        data.update({
            'text': context.user_data.get('message'),
            'user_name': context.user_data.get('user_name')
        })

    try:
        # Зберігаємо
        await db.create_feedback(data)

        success_text = (
            f"✅ <b>Подяка успішно надіслана!</b>\n\n"
            f"🆔 <b>Номер звернення:</b> <code>{reg_number}</code>\n"
            f"🙏 Дякуємо, що допомагаєте нам ставати кращими!"
        )
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text=success_text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
            ),
            parse_mode=ParseMode.HTML
        )
        logger.info(f"Thanks saved: {reg_number}")

    except Exception as e:
        logger.error(f"Save error: {e}")
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text="❌ Помилка збереження."
        )

    context.user_data.pop('thanks_type', None)
    context.user_data.pop('transport_type', None)
    context.user_data.pop('board_number', None)
    context.user_data.pop('reason', None)
    context.user_data.pop('message', None)
    context.user_data.pop('user_name', None)
    context.user_data.pop('phone', None)
    context.user_data.pop('email', None)

    return ConversationHandler.END


# ============================================
# РЕЄСТРАЦІЯ
# ============================================

def register_thanks_handlers():
    return {
        'entry_points': [('callback', 'thanks', thanks_start)],
        'states': {
            States.THANKS_CHOOSE_TYPE: [
                ('callback', 'thanks:specific', thanks_specific_type_selection),
                ('callback', 'thanks:general', thanks_general_start),
            ],
            States.THANKS_SPECIFIC_CHOOSE_TRANSPORT: [
                ('callback', 'thanks:transport:.*', thanks_transport_selected),
            ],
            States.THANKS_SPECIFIC_BOARD_NUMBER: [
                ('message', None, thanks_board_number_input),
                ('callback', 'thanks:skip_board', thanks_skip_board)
            ],
            States.THANKS_SPECIFIC_REASON: [('message', None, thanks_reason_input)],
            
            States.THANKS_SPECIFIC_PHONE: [
                ('message', None, thanks_phone_step),
                ('callback', 'thanks:skip_phone', thanks_phone_step)
            ],
            States.THANKS_GENERAL_PHONE: [
                ('message', None, thanks_phone_step),
                ('callback', 'thanks:skip_phone', thanks_phone_step)
            ],

            States.THANKS_SPECIFIC_EMAIL: [
                ('message', None, thanks_input_email_and_confirm),
                ('callback', 'thanks:skip_email', thanks_input_email_and_confirm)
            ],
            States.THANKS_GENERAL_EMAIL: [
                ('message', None, thanks_input_email_and_confirm),
                ('callback', 'thanks:skip_email', thanks_input_email_and_confirm)
            ],

            States.THANKS_GENERAL_MESSAGE: [('message', None, thanks_general_message)],
            States.THANKS_GENERAL_NAME: [('message', None, thanks_general_name)],

            States.THANKS_CONFIRMATION: [
                ('callback', 'confirm_send', thanks_confirm_save),
                ('callback', 'thanks', thanks_start),
            ]
        },
        'fallbacks': [
            ('callback', 'feedback_menu', thanks_start),
            ('callback', 'main_menu', thanks_start)
        ]
    }