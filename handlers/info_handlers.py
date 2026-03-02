from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from config.messages import MESSAGES
from handlers.common import get_back_keyboard
from utils.logger import logger
from config.settings import RULES_PDF_PATH




async def show_info_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує меню 'Довідкова інформація'."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("📜 Правила користування", callback_data="info:rules")],
        [InlineKeyboardButton("♿ Доступність (Інклюзивність)", callback_data="info:accessibility")],
        [InlineKeyboardButton("📞 Контакти", callback_data="info:contacts")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    # Визначаємо текст та клавіатуру заздалегідь
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "ℹ️ Розділ 'Довідкова інформація'. Оберіть опцію:"

    # --- ПОЧАТОК ВИПРАВЛЕННЯ --- 03.11.2025 10:01

    # Ми перевіряємо, чи є у повідомлення, з якого натиснули кнопку,
    # текстовий вміст (query.message.text).
    if query.message.text:
        # Якщо ТАК (наприклад, ми прийшли з головного меню),
        # ми можемо безпечно редагувати текст.
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup
        )
    else:
        # Якщо НІ (це означає, що ми прийшли з повідомлення без тексту,
        # як-от наш PDF-документ), ми не можемо його "відредагувати".
        # Тому спочатку надсилаємо нове текстове повідомлення з меню "Довідка"...
        await query.message.reply_text(
            text=text,
            reply_markup=reply_markup
        )
        # ...а вже потім акуратно видаляємо повідомлення з PDF, щоб уникнути «порожнього» екрану.
        try:
            await query.message.delete()
        except Exception:
            pass
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ --- 03.11.2025 10:01



async def send_rules_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Надсилає PDF-файл з правилами користування."""
    query = update.callback_query
    await query.answer()

    keyboard = await get_back_keyboard("info_menu")
    caption_text = MESSAGES.get("info_rules")

    try:
        # 1. Спочатку надсилаємо документ користувачу
        with open(RULES_PDF_PATH, 'rb') as document:
            await query.message.reply_document(
                document=document,
                filename="Pravyla_OMET.pdf",  # Назва файлу, яку побачить користувач
                caption=caption_text,
                reply_markup=keyboard
            )

        # 2. Після цього пробуємо видалити старе меню \"Довідка\",
        # щоб уникнути короткого періоду без жодного повідомлення.
        try:
            await query.message.delete()
        except Exception:
            pass
        logger.info("✅ Rules PDF sent successfully")

    except FileNotFoundError:
        logger.error(f"❌ PDF file not found: {RULES_PDF_PATH}")
        await query.message.reply_text(
            "❌ Файл з правилами не знайдено. Спробуйте пізніше.",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"❌ Error sending rules PDF: {e}")
        await query.message.reply_text(
            "❌ Сталася помилка при завантаженні файлу.",
            reply_markup=keyboard
        )

async def handle_info_static(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє всі статичні під-меню 'Довідки'."""
    query = update.callback_query
    await query.answer()

    key = query.data.split(":")[1]

    # 'rules' тепер обробляється окремою функцією
    if key == "rules":
        logger.warning("handle_info_static received 'rules' key. Ignored.")
        return

    # 'rules' обробляється send_rules_pdf, 'routes' видалено
    text = MESSAGES.get(f"info_{key}", "Інформація не знайдена.")

    keyboard = await get_back_keyboard("info_menu")
    await query.edit_message_text(
        text=text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML  # <-- ДОДАЛИ АРГУМЕНТ ДЛЯ ОБРОБКИ
    )