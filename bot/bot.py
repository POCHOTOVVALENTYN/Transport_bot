import logging
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler
)
from handlers.command_handlers import cmd_start, cmd_help
from handlers.complaint_handlers import (
    complaint_start, complaint_get_route, complaint_get_board,
    complaint_get_datetime, complaint_get_contact, complaint_save,
    thanks_start, thanks_get_route, thanks_get_board, thanks_save,
    States
)
from handlers.menu_handlers import main_menu

logger = logging.getLogger(__name__)


class TransportBot:
    """Головний клас бота"""

    def __init__(self, token: str):
        self.token = token
        self.app = Application.builder().token(token).build()
        self._setup_handlers()

    def _setup_handlers(self):
        """Налаштування всіх обробників"""

        logger.info("🔧 Setting up handlers...")

        # Команди
        self.app.add_handler(CommandHandler("start", cmd_start))
        self.app.add_handler(CommandHandler("help", cmd_help))

        # Menu callbacks
        self.app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))

        # CONVERSATION: СКАРГИ
        complaint_conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(complaint_start, pattern="^complaint$")
            ],
            states={
                States.PROBLEM: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_get_route)
                ],
                States.ROUTE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_get_board)
                ],
                States.BOARD: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_get_datetime)
                ],
                States.DATETIME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_get_contact)
                ],
                States.CONTACT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_save)
                ],
            },
            fallbacks=[
                CallbackQueryHandler(main_menu, pattern="^main_menu$")
            ]
        )

        # CONVERSATION: ПОДЯКИ
        thanks_conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(thanks_start, pattern="^thanks$")
            ],
            states={
                States.PROBLEM: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, thanks_get_route)
                ],
                States.ROUTE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, thanks_get_board)
                ],
                States.BOARD: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, thanks_save)
                ],
            },
            fallbacks=[
                CallbackQueryHandler(main_menu, pattern="^main_menu$")
            ]
        )

        # Додавання conversation handlers
        self.app.add_handler(complaint_conv)
        self.app.add_handler(thanks_conv)

        logger.info("✅ All handlers configured")

    async def start(self):
        """Запуск бота"""
        logger.info("🚀 Starting bot polling...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

    async def stop(self):
        """Зупинка бота"""
        logger.info("⛔ Stopping bot...")
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()