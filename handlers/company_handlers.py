from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from config.messages import MESSAGES
from handlers.common import get_back_keyboard
from utils.logger import logger
from telegram.constants import ParseMode
from config.settings import RENTAL_SERVICE_IMAGE
from services.vacancy_service import VacancyService, encode_vacancy_url

# Вакансії тепер керуються з адмін-панелі й зберігаються в таблиці `vacancies` (database/db.py).
# Початкові дані перенесено туди при першому запуску (див. init_db у database/db.py).
vacancy_service = VacancyService()


async def show_company_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує меню 'Про підприємство'."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        # Припускаю, що "Вакансії" та "Навчання" вже перенесені
        [InlineKeyboardButton("🏛️ Історія та сучасність", callback_data="company:history")],
        [InlineKeyboardButton("🚌 Оренда та послуги", callback_data="company:services")],
        [InlineKeyboardButton("📰 Новини / Соц. мережі", callback_data="company:socials")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🏢 Розділ 'Про підприємство'. Оберіть опцію:"

    # 1. Спроба "м'якого" редагування (якщо ми переходимо з текстового розділу)
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        # Якщо редагування вдалося - виходимо, все ок.
        return
    except Exception:
        # Якщо не вийшло (значить попереднє повідомлення було з фото або його не можна редагувати)
        pass

    # 2. План Б (Анти-миготіння): Спочатку надсилаємо нове, потім видаляємо старе
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    # 3. Тепер чистимо "хвости" (фото та старе повідомлення)
    try:
        await query.message.delete()
    except:
        pass

    if 'media_message_ids' in context.user_data:
        for msg_id in context.user_data['media_message_ids']:
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
            except Exception:
                pass
        del context.user_data['media_message_ids']



async def show_history_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує інформацію про Історію підприємства."""
    query = update.callback_query
    await query.answer()

    text = MESSAGES.get("company_history")

    # Створюємо клавіатуру з посиланням та кнопками навігації
    keyboard = [
        [InlineKeyboardButton("📖 Дізнатися більше на сайті", url="https://oget.od.ua/about")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="company_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


async def show_services_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Надсилає ОДНЕ фото з підписом та кнопками про Оренду.
    Використовує 'Loading...' для плавного переходу.
    """
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_chat.id
    caption_text = MESSAGES.get("company_services")

    keyboard = [
        [InlineKeyboardButton("🔗 Детальніше на сайті", url="https://oget.od.ua/orenda-transportu/")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="company_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # 1. АНТИ-БЛИМАННЯ: Редагуємо текст на "Завантажую..." замість видалення
    # Це утримує екран, поки ми возимося з файлом фото
    try:
        loading_msg = await query.edit_message_text(
            text="⏳ <b>Завантажую інформацію...</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        # Якщо редагування не вдалося (рідкісний випадок), надсилаємо нове
        loading_msg = await query.message.reply_text("⏳ Завантажую...")

    try:
        # 2. Відкриваємо і надсилаємо фото
        with open(RENTAL_SERVICE_IMAGE, 'rb') as photo:
            sent_msg = await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )

        # 3. Зберігаємо ID фото (щоб кнопка "Назад" могла його видалити, як в інших меню)
        context.user_data['media_message_ids'] = [sent_msg.message_id]

        # 4. Видаляємо повідомлення "Завантажую..."
        await context.bot.delete_message(chat_id=chat_id, message_id=loading_msg.message_id)

        logger.info("✅ Rental info (single photo) sent successfully")

    except FileNotFoundError:
        logger.error(f"❌ Rental photo file not found: {RENTAL_SERVICE_IMAGE}")
        # Якщо фото немає, редагуємо "Завантажую" на текст помилки/інфо
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading_msg.message_id,
            text=f"❌ Фото не знайдено, але ось інформація:\n\n{caption_text}",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"❌ Error sending rental info: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading_msg.message_id,
            text="❌ Сталася технічна помилка при завантаженні.",
            reply_markup=reply_markup
        )

async def show_history_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує інформацію про Історію підприємства."""
    query = update.callback_query
    await query.answer()

    text = MESSAGES.get("company_history")

    # Створюємо клавіатуру з посиланням та кнопками навігації
    keyboard = [
        [InlineKeyboardButton("📖 Дізнатися більше на сайті", url="https://oget.od.ua/about")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="company_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def show_education_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показує інформацію про 'Навчально-курсовий комбінат'.
    (Викликається з Головного меню)
    """
    query = update.callback_query
    await query.answer()

    text = MESSAGES.get("company_education", "Інформація не знайдена.")

    # Кнопка "Назад" тепер веде до Головного меню
    keyboard = await get_back_keyboard("main_menu")

    await query.edit_message_text(
        text=text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )


async def handle_company_static(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє статичні під-меню 'Про підприємство' (зараз - лише 'Соц. мережі')."""
    query = update.callback_query
    await query.answer()

    # Отримуємо текст
    text = MESSAGES.get("company_socials", "Інформація не знайдена.")

    # Створюємо нову клавіатуру з вашими посиланнями
    keyboard = [
        [InlineKeyboardButton("🖥️ Офіційний сайт", url="https://oget.od.ua")],
        [InlineKeyboardButton("📸 Instagram", url="https://www.instagram.com/kp_omet")],
        [InlineKeyboardButton("📘 Facebook", url="https://www.facebook.com/kp.oget/?locale=uk_UA")],
        # Додаємо стандартні кнопки навігації
        [InlineKeyboardButton("⬅️ Назад", callback_data="company_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True # Рекомендую, щоб уникнути 4 превʼю в повідомленні
    )


async def show_vacancies_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує під-меню 'Вакансії'."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("👷 З досвідом", callback_data="vacancy_type:experienced")],
        [InlineKeyboardButton("🧑‍🎓 Без досвіду (навчання)", callback_data="vacancy_type:trainee")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        text="👔 Оберіть категорію вакансій:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_vacancy_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує список активних вакансій з бази даних (керовані адміністратором)."""
    query = update.callback_query
    await query.answer()

    v_type = query.data.split(":")[1]
    keyboard = []
    text = "👇 Оберіть вакансію, щоб перейти до повного опису на сайті:"
    if v_type == "trainee":
        text = "Навчання з подальшим працевлаштуванням:\n👇 Оберіть вакансію:"

    vacancies = await vacancy_service.get_active_vacancies(v_type)

    if not vacancies:
        text = "😔 Наразі немає активних вакансій у цій категорії. Спробуйте пізніше."
    else:
        for vacancy in vacancies:
            if vacancy.contact_type == "phone":
                # Телефон рендеримо через tel:-схему, інакше Telegram відхилить URL кнопки
                contact_value = vacancy.contact_value.strip()
                button_url = contact_value if contact_value.startswith("tel:") else f"tel:{contact_value}"
            else:
                # Кирилиця у шляху URL ламає валідацію кнопки в Telegram Bot API — кодуємо.
                button_url = encode_vacancy_url(vacancy.contact_value)
            label = f"👷 {vacancy.title}" if v_type == "experienced" else vacancy.title
            keyboard.append([InlineKeyboardButton(label, url=button_url)])

    # Кнопки навігації
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="vacancies_menu")])
    keyboard.append([InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")])

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True # Щоб уникнути безладу з прев'ю
    )

