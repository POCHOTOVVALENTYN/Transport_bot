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

    # Переходимо до Email (обов'язково)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ])
    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text="✉️ <b>Введіть Ваш Email</b> для зворотного зв'язку (обов'язково):",
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
    Цей хендлер ловить введення Email (обов'язково),
    та переходить до вибору потреби у відповіді.
    """
    is_callback = update.callback_query is not None

    if is_callback:
        query = update.callback_query
        await query.answer("Цей крок є обов'язковим!", show_alert=True)
        thanks_type = context.user_data.get('thanks_type')
        return States.THANKS_SPECIFIC_EMAIL if thanks_type == 'specific' else States.THANKS_GENERAL_EMAIL

    await update.message.delete()
    raw_email = update.message.text.strip()

    if not validate_email(raw_email):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
        ])
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text="❌ Невірний формат Email. Будь ласка, спробуйте ще раз:",
            reply_markup=kb
        )
        thanks_type = context.user_data.get('thanks_type')
        return States.THANKS_SPECIFIC_EMAIL if thanks_type == 'specific' else States.THANKS_GENERAL_EMAIL

    email = raw_email
    context.user_data['email'] = email
    return await thanks_ask_response_need(update, context)


async def thanks_ask_response_need(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Запит чи потрібна відповідь на подяку"""
    prompt = (
        "❓ <b>Чи потрібна вам офіційна відповідь на це звернення?</b>\n\n"
        "Оберіть зручний для вас варіант нижче 👇"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📧 Так, електронною поштою", callback_data="thanks_resp:email")],
        [InlineKeyboardButton("📮 Так, паперовим листом (Укрпошта)", callback_data="thanks_resp:mail")],
        [InlineKeyboardButton("❌ Ні, відповідь не потрібна", callback_data="thanks_resp:no")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ])
    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text=prompt,
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return States.THANKS_RESPONSE_NEED


async def thanks_response_need_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка вибору потреби у відповіді"""
    query = update.callback_query
    await query.answer()

    choice = query.data.split(":")[1]
    context.user_data['thanks_need_response'] = choice

    if choice == "mail":
        prompt = (
            "🏠 <b>Вкажіть Вашу домашню адресу</b>\n\n"
            "Будь ласка, введіть Вашу повну поштову адресу (вулиця, будинок, квартира, місто, область, поштовий індекс) для відправки відповіді паперовим листом:"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
        ])
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text=prompt,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
        return States.THANKS_HOME_ADDRESS
    else:
        context.user_data['thanks_home_address'] = None
        return await thanks_show_confirm(update, context)


async def thanks_home_address_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання домашньої адреси"""
    await update.message.delete()
    address = update.message.text.strip()
    context.user_data['thanks_home_address'] = address
    return await thanks_show_confirm(update, context)


async def thanks_show_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Формує звіт і показує екран підтвердження"""
    thanks_type = context.user_data.get('thanks_type')
    phone = context.user_data.get('phone', 'Не вказано')
    email = context.user_data.get('email', 'Не вказано')
    need_resp = context.user_data.get('thanks_need_response', 'no')
    home_address = context.user_data.get('thanks_home_address')

    need_resp_ua = (
        "Так (Email) 📧" if need_resp == "email"
        else "Так (Пошта) 📮" if need_resp == "mail"
        else "Ні ❌"
    )

    if thanks_type == 'specific':
        summary = (
            f"🔍 <b>Перевірте Ваші дані:</b>\n\n"
            f"📌 <b>Тип:</b> Конкретне звернення ({context.user_data.get('transport_type')})\n"
            f"🔢 <b>Борт. номер:</b> {context.user_data.get('board_number')}\n"
            f"✍️ <b>Текст:</b> {context.user_data.get('reason')}\n"
            f"📞 <b>Телефон:</b> {phone}\n"
            f"📧 <b>Email:</b> {email}\n"
            f"❓ <b>Потрібна відповідь:</b> {need_resp_ua}\n"
        )
    else:
        summary = (
            f"🔍 <b>Перевірте Ваші дані:</b>\n\n"
            f"📌 <b>Тип:</b> Загальне звернення\n"
            f"👤 <b>Ім'я:</b> {context.user_data.get('user_name')}\n"
            f"✍️ <b>Текст:</b> {context.user_data.get('message')}\n"
            f"📞 <b>Телефон:</b> {phone}\n"
            f"📧 <b>Email:</b> {email}\n"
            f"❓ <b>Потрібна відповідь:</b> {need_resp_ua}\n"
        )

    if need_resp == "mail" and home_address:
        summary += f"🏠 <b>Адреса:</b> {home_address}\n"

    summary += "\nВсе вірно?"

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
        'need_response': context.user_data.get('thanks_need_response', 'no'),
        'home_address': context.user_data.get('thanks_home_address'),
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
        # Зберігаємо та отримуємо справжній ticket_id з БД
        ticket_id = await db.create_feedback(data)

        # Надсилаємо картку модерації адмінам
        from handlers.admin_handlers import send_moderation_card_to_admins
        await send_moderation_card_to_admins(context.bot, ticket_id)

        success_text = (
            f"✅ <b>Подяка успішно надіслана!</b>\n\n"
            f"🆔 <b>Номер звернення:</b> <code>{ticket_id}</code>\n"
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
    context.user_data.pop('thanks_need_response', None)
    context.user_data.pop('thanks_home_address', None)

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