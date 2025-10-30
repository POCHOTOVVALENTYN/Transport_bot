import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from services.tickets_service import TicketsService
from config.messages import MESSAGES
from utils.logger import logger


# Стани
class States:
    PROBLEM = 1
    ROUTE = 2
    BOARD = 3
    DATETIME = 4
    CONTACT = 5


# ===== СКАРГИ =====

async def complaint_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок скарги"""
    logger.info(f"User {update.effective_user.id} started complaint")
    await update.callback_query.edit_message_text(text=MESSAGES['complaint_start'])
    return States.PROBLEM


async def complaint_get_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання проблеми"""
    context.user_data['complaint_problem'] = update.message.text
    logger.info(f"Problem: {update.message.text[:50]}")
    await update.message.reply_text(MESSAGES['complaint_route'])
    return States.ROUTE


async def complaint_get_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання маршруту"""
    context.user_data['complaint_route'] = update.message.text
    logger.info(f"Route: {update.message.text}")
    await update.message.reply_text(MESSAGES['complaint_board'])
    return States.BOARD


async def complaint_get_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання борта"""
    context.user_data['complaint_board'] = update.message.text
    logger.info(f"Board: {update.message.text}")
    await update.message.reply_text(MESSAGES['complaint_datetime'])
    return States.DATETIME


async def complaint_get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання дати"""
    context.user_data['complaint_datetime'] = update.message.text
    logger.info(f"DateTime: {update.message.text}")
    await update.message.reply_text(MESSAGES['complaint_contact'])
    return States.CONTACT


async def complaint_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Збереження скарги"""
    contact_parts = update.message.text.split(',')
    user_name = contact_parts[0].strip()
    user_phone = contact_parts[1].strip() if len(contact_parts) > 1 else "N/A"

    complaint_data = {
        "problem": context.user_data.get('complaint_problem'),
        "route": context.user_data.get('complaint_route'),
        "board_number": context.user_data.get('complaint_board'),
        "incident_datetime": context.user_data.get('complaint_datetime'),
        "user_name": user_name,
        "user_phone": user_phone
    }

    try:
        service = TicketsService()
        result = await service.create_complaint_ticket(
            telegram_id=update.effective_user.id,
            complaint_data=complaint_data
        )

        if result['success']:
            keyboard = [
                [InlineKeyboardButton("📊 Статус", callback_data=f"check:{result['ticket_id']}")],
                [InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]
            ]
            await update.message.reply_text(result['message'], reply_markup=InlineKeyboardMarkup(keyboard))
            logger.info(f"Complaint saved: {result['ticket_id']}")
        else:
            await update.message.reply_text(result['message'])
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ Помилка")

    return ConversationHandler.END


# ===== ПОДЯКИ =====

async def thanks_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок подяки"""
    logger.info(f"User {update.effective_user.id} started thanks")
    await update.callback_query.edit_message_text(text="❤️ Напишіть, за що дякуєте:")
    return States.PROBLEM


async def thanks_get_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання тексту подяки"""
    context.user_data['thanks_text'] = update.message.text
    logger.info(f"Thanks: {update.message.text[:50]}")
    await update.message.reply_text("Маршрут (або 'n'):")
    return States.ROUTE


async def thanks_get_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання маршруту подяки"""
    route = update.message.text if update.message.text.lower() != "n" else None
    context.user_data['thanks_route'] = route
    logger.info(f"Thanks route: {route}")
    await update.message.reply_text("Борт №  (або 'n'):")
    return States.BOARD


async def thanks_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Збереження подяки"""
    board = update.message.text if update.message.text.lower() != "n" else None

    try:
        service = TicketsService()
        result = await service.create_thanks_ticket(
            telegram_id=update.effective_user.id,
            text=context.user_data.get('thanks_text'),
            route=context.user_data.get('thanks_route'),
            board_number=board
        )

        if result['success']:
            keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]]
            await update.message.reply_text(result['message'], reply_markup=InlineKeyboardMarkup(keyboard))
            logger.info(f"Thanks saved: {result['ticket_id']}")
        else:
            await update.message.reply_text(result['message'])
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ Помилка")

    return ConversationHandler.END