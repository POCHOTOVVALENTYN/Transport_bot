from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from config.messages import MESSAGES
from handlers.common import get_back_keyboard
import logging
from config.settings import RULES_PDF_PATH

logger = logging.getLogger(__name__)


async def show_info_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує меню 'Довідкова інформація'."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🗺️ Наші маршрути (схеми)", callback_data="info:routes")],
        [InlineKeyboardButton("📜 Правила користування", callback_data="info:rules")],
        [InlineKeyboardButton("♿ Доступність (Інклюзивність)", callback_data="info:accessibility")],
        [InlineKeyboardButton("📞 Контакти", callback_data="info:contacts")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        text="ℹ️ Розділ 'Довідкова інформація'. Оберіть опцію:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def send_rules_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Надсилає PDF-файл з правилами користування."""
    query = update.callback_query
    await query.answer()

    keyboard = await get_back_keyboard("info_menu")
    caption_text = MESSAGES.get("info_rules")

    try:
        # 1. Видаляємо поточне повідомлення (меню "Довідка")
        await query.delete_message()

        # 2. Надсилаємо документ
        with open(RULES_PDF_PATH, 'rb') as document:
            await query.message.reply_document(
                document=document,
                filename="Pravyla_OMET.pdf",  # Назва файлу, яку побачить користувач
                caption=caption_text,
                reply_markup=keyboard
            )
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

    if key == "routes":
        text = MESSAGES.get("info_routes", "Тут буде список маршрутів...")
    elif key == "rules":
        text = MESSAGES.get("info_rules", "Тут буде PDF з правилами...")
    else:
        text = MESSAGES.get(f"info_{key}", "Інформація не знайдена.")

    keyboard = await get_back_keyboard("info_menu")
    await query.edit_message_text(text=text, reply_markup=keyboard)