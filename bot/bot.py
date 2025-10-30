# bot/bot.py
import logging
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler
)

# --- Старі імпорти ---
from handlers.command_handlers import cmd_start, cmd_help
from handlers.complaint_handlers import (
    complaint_start, complaint_get_route, complaint_get_board,
    complaint_get_datetime, complaint_get_contact, complaint_save,
    thanks_start, thanks_get_route, thanks_get_board, thanks_save,
)
from handlers.menu_handlers import main_menu

# --- НОВІ ІМПОРТИ ---
from bot.states import States
from handlers.static_handlers import (
    realtime_transport, lost_items
)
from handlers.feedback_handlers import show_feedback_menu
from handlers.tickets_handlers import (
    show_tickets_menu, handle_ticket_static, show_passes_list
)
from handlers.info_handlers import show_info_menu, handle_info_static
from handlers.company_handlers import (
    show_company_menu, handle_company_static, show_vacancies_menu,
    show_vacancy_list, show_vacancy_details
)
from handlers.museum_handlers import (
    show_museum_menu, handle_museum_static, museum_register_start,
    museum_get_date, museum_get_people_count, museum_save_registration
)
from handlers.suggestion_handlers import (
    suggestion_start, suggestion_get_text, suggestion_save, suggestion_skip_contact
)

# --- КІНЕЦЬ НОВИХ ІМПОРТІВ ---

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

        # --- КОМАНДИ ---
        self.app.add_handler(CommandHandler("start", cmd_start))
        self.app.add_handler(CommandHandler("help", cmd_help))

        # --- ГОЛОВНЕ МЕНЮ ---
        self.app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))

        # --- ОБРОБНИКИ МЕНЮ 1-ГО РІВНЯ ---
        self.app.add_handler(CallbackQueryHandler(show_tickets_menu, pattern="^tickets_menu$"))
        self.app.add_handler(CallbackQueryHandler(realtime_transport, pattern="^realtime_transport$"))
        self.app.add_handler(CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"))
        self.app.add_handler(CallbackQueryHandler(show_info_menu, pattern="^info_menu$"))
        self.app.add_handler(CallbackQueryHandler(show_museum_menu, pattern="^museum_menu$"))
        self.app.add_handler(CallbackQueryHandler(show_company_menu, pattern="^company_menu$"))

        # --- ОБРОБНИКИ 2-ГО+ РІВНЯ (РОУТЕРИ) ---
        self.app.add_handler(CallbackQueryHandler(show_passes_list, pattern="^tickets:passes$"))
        self.app.add_handler(CallbackQueryHandler(handle_ticket_static, pattern="^tickets:"))
        self.app.add_handler(CallbackQueryHandler(handle_info_static, pattern="^info:"))
        self.app.add_handler(CallbackQueryHandler(handle_museum_static,
                                                  pattern="^museum:"))  # Обережно: не має перетинатись з 'museum:register_start'

        # Обробники "Про підприємство" (складніші)
        self.app.add_handler(
            CallbackQueryHandler(handle_company_static, pattern="^company:(education|services|socials)$"))
        self.app.add_handler(CallbackQueryHandler(show_vacancies_menu, pattern="^company:vacancies$"))
        self.app.add_handler(CallbackQueryHandler(show_vacancy_list, pattern="^vacancy_type:"))
        self.app.add_handler(CallbackQueryHandler(show_vacancy_details, pattern="^vacancy:"))

        # Обробник "Загублені речі"
        self.app.add_handler(CallbackQueryHandler(lost_items, pattern="^lost_items$"))

        # CONVERSATION: СКАРГИ (існуючий)
        # --- CONVERSATION HANDLERS ---

        # CONVERSATION: СКАРГИ (існуючий)
        complaint_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(complaint_start, pattern="^complaint$", block=False)],
            # <-- ДОДАНО block=False
            states={
                States.COMPLAINT_PROBLEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_get_route)],
                States.COMPLAINT_ROUTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_get_board)],
                States.COMPLAINT_BOARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_get_datetime)],
                States.COMPLAINT_DATETIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_get_contact)],
                States.COMPLAINT_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_save)],
            },
            fallbacks=[CallbackQueryHandler(main_menu, pattern="^main_menu$")]
        )

        # CONVERSATION: ПОДЯКИ (існуючий)
        thanks_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(thanks_start, pattern="^thanks$", block=False)],
            # <-- ДОДАНО block=False
            states={
                States.THANKS_PROBLEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, thanks_get_route)],
                States.THANKS_ROUTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, thanks_get_board)],
                States.THANKS_BOARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, thanks_save)],
            },
            fallbacks=[CallbackQueryHandler(main_menu, pattern="^main_menu$")]
        )

        # NEW CONVERSATION: ПРОПОЗИЦІЇ
        suggestion_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(suggestion_start, pattern="^suggestion$", block=False)],
            # <-- ДОДАНО block=False
            states={
                States.SUGGESTION_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, suggestion_get_text)],
                States.SUGGESTION_CONTACT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, suggestion_save),
                    CommandHandler("skip", suggestion_skip_contact)
                ],
            },
            fallbacks=[CallbackQueryHandler(main_menu, pattern="^main_menu$")]
        )

        # NEW CONVERSATION: РЕЄСТРАЦІЯ В МУЗЕЙ
        museum_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(museum_register_start, pattern="^museum:register_start$", block=False)],
            # <-- ДОДАНО block=False
            states={
                States.MUSEUM_DATE: [CallbackQueryHandler(museum_get_date, pattern="^museum_date:")],
                States.MUSEUM_PEOPLE_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, museum_get_people_count)],
                States.MUSEUM_CONTACT_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, museum_save_registration)],
            },
            # 'fallbacks' повертає до меню музею, а не головного
            fallbacks=[CallbackQueryHandler(show_museum_menu, pattern="^museum_menu$")]
        )

        # Додавання всіх conversation handlers
        self.app.add_handler(complaint_conv)
        self.app.add_handler(thanks_conv)
        self.app.add_handler(suggestion_conv)
        self.app.add_handler(museum_conv)

        logger.info("✅ All handlers configured")

    def start(self):
        logger.info("🚀 Starting bot polling...")
        self.app.run_polling()

    async def stop(self):
        """Зупинка бота"""
        # ... (код без змін) ...