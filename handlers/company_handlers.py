from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from config.messages import MESSAGES
from handlers.common import get_back_keyboard
import logging
from telegram.constants import ParseMode
from config.settings import RENTAL_SERVICE_IMAGE


logger = logging.getLogger(__name__)

# База даних вакансій (з досвідом)
EXPERIENCED_VACANCIES = {
    "Провідний фахівець з публічних закупівель": "https://www.work.ua/jobs/6542926/",
    "Фахівець з публічних закупівель": "https://oget.od.ua/jobs/фахівець-з-публічних-закупівель",
    "Зварювальник": "https://oget.od.ua/jobs/зварювальник",
    "Слюсар з ремонту рухомого складу": "https://oget.od.ua/jobs/слюсар-з-ремонту-рухомого-складу",
    "Електрогазозварник": "https://oget.od.ua/jobs/електрогазозварник",
    "Електромонтер контактної/кабельної мережі": "https://oget.od.ua/jobs/електромонтер-контактної-та-кабельн",
    "Електромонтер тягової підстанції": "https://oget.od.ua/jobs/слюсар-електрик-з-ремонту-електроуст",
    "Слюсар-електрик з ремонту електроустаткування": "https://oget.od.ua/jobs/слюсар-електрик-з-ремонту-електроуст-2"
}


# База даних вакансій (без досвіду / навчання)
TRAINEE_VACANCIES = {
    "👩‍💼 Кондуктор": "https://oget.od.ua/jobs/кондуктор",
    "🧼 Мийник-прибиральник рухомого складу": "https://oget.od.ua/jobs/мийник-прибиральник-рухомого-складу",
    "🛠️ Монтер колії 3 розряд": "https://oget.od.ua/jobs/монтер-колії-234-розряд"
}

async def show_company_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує меню 'Про підприємство'."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        # Припускаю, що "Вакансії" та "Навчання" вже перенесені
        [InlineKeyboardButton("🚌 Оренда та послуги", callback_data="company:services")],
        [InlineKeyboardButton("📰 Новини / Соц. мережі", callback_data="company:socials")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🏢 Розділ 'Про підприємство'. Оберіть опцію:"

    # --- ПОЧАТОК ВИПРАВЛЕННЯ (Логіка Edit/Delete) ---
    if query.message.text:
        # Якщо ми прийшли з текстового меню (Головне меню)
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup
        )
    else:
        # Якщо ми прийшли з медіа (фото оренди)
        await query.message.delete()
        await query.message.reply_text(
            text=text,
            reply_markup=reply_markup
        )
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

async def show_services_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Надсилає ОДНЕ фото з підписом та кнопками про Оренду."""
    query = update.callback_query
    await query.answer()

    caption_text = MESSAGES.get("company_services")

    keyboard = [
        [InlineKeyboardButton("🔗 Детальніше на сайті", url="https://oget.od.ua/orenda-transportu/")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="company_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        # 1. Видаляємо поточне повідомлення (меню "Про підприємство")
        await query.delete_message()

        # 2. Надсилаємо ОДНЕ фото з підписом та кнопками
        with open(RENTAL_SERVICE_IMAGE, 'rb') as photo:
            await query.message.reply_photo(
                photo=photo,
                caption=caption_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        logger.info("✅ Rental info (single photo) sent successfully")

    except FileNotFoundError:
        logger.error(f"❌ Rental photo file not found: {RENTAL_SERVICE_IMAGE}")
        # Відправляємо текст, якщо фото не знайдено
        await query.message.reply_text(
            text=f"❌ Файл з фото не знайдено.\n\n{caption_text}",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"❌ Error sending rental info: {e}")
        await query.message.reply_text(
            "❌ Сталася помилка при завантаженні інформації.",
            reply_markup=reply_markup
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
        disable_web_page_preview=True # Рекомендую, щоб уникнути 4 прев'ю в повідомленні
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
    """Показує список вакансій з посиланнями на сайт."""
    query = update.callback_query
    await query.answer()

    v_type = query.data.split(":")[1]
    keyboard = []
    text = "👇 Оберіть вакансію, щоб перейти до повного опису на сайті:"

    if v_type == "experienced":
        for name, url in EXPERIENCED_VACANCIES.items():
            keyboard.append([InlineKeyboardButton(f"👷 {name}", url=url)])

    elif v_type == "trainee":
        text = "Навчання з подальшим працевлаштуванням:\n👇 Оберіть вакансію:"
        for name, url in TRAINEE_VACANCIES.items():

            keyboard.append([InlineKeyboardButton(name, url=url)])

    # Кнопки навігації
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="vacancies_menu")])
    keyboard.append([InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")])

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True # Щоб уникнути безладу з прев'ю
    )

