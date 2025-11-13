# bot/bot.py

from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler
)

# --- Старі імпорти ---
from handlers.command_handlers import cmd_start, cmd_help
from handlers.complaint_handlers import (
    complaint_start_simplified, complaint_save_simplified
)
from handlers.menu_handlers import main_menu

# --- НОВІ ІМПОРТИ ---
from bot.states import States

from handlers.accessible_transport_handlers import (
    accessible_start,
    accessible_show_routes,
    accessible_request_location,
    accessible_process_stub,
    accessible_notify_me,
    #accessible_notify_me_stub,
    accessible_text_cancel,
    load_easyway_route_ids # <-- НОВИЙ ВАЖЛИВИЙ ІМПОРТ
)

from handlers.static_handlers import (
    realtime_transport, lost_items
)
from handlers.feedback_handlers import show_feedback_menu
from handlers.tickets_handlers import (
    show_tickets_menu, handle_ticket_static, show_passes_list
)
from handlers.info_handlers import (
    show_info_menu, handle_info_static, send_rules_pdf
)
from handlers.company_handlers import (
    show_company_menu, handle_company_static, show_vacancies_menu,
    show_vacancy_list, show_education_menu, show_services_menu,
    show_history_menu
)
from handlers.museum_handlers import (
    show_museum_menu, handle_museum_static, museum_register_start,
    museum_get_date, museum_get_people_count, museum_get_name,
    museum_get_phone_and_save, show_museum_info
)
from handlers.thanks_handlers import (
    thanks_start, thanks_ask_specific, thanks_get_route,
    thanks_get_board, thanks_ask_name, thanks_get_name, thanks_save
)

from handlers.suggestion_handlers import (
    suggestion_start, suggestion_ask_contact, suggestion_get_name,
    suggestion_get_phone, suggestion_get_email, suggestion_save_with_email,
    suggestion_save_skip_email # <-- 'suggestion_save_anonymously' видалено
)


from handlers.admin_handlers import (
    admin_menu, admin_add_date_start, admin_add_date_save,
    admin_del_date_menu, admin_del_date_confirm, admin_menu_show,
    admin_show_bookings # Нова функція зі списком
)

from utils.logger import logger


class TransportBot:
    """Головний клас бота"""

    def __init__(self, token: str):
        self.token = token

        # 1. ЗАЛИШАЄМО ТІЛЬКИ ОДИН РЯДОК Application.builder
        #    з реєстрацією `post_init`.
        self.app = Application.builder().token(token).build()

        # Рядок (self.app = Application.builder().token(token).build()) ВИДАЛЕНО

        self._setup_handlers()


    def _setup_handlers(self):
        """Налаштування всіх обробників"""
        logger.info("🔧 Setting up handlers...")

        # --- КОМАНДИ ---
        self.app.add_handler(CommandHandler("start", cmd_start))
        self.app.add_handler(CommandHandler("help", cmd_help))

        ## CONVERSATION: СКАРГИ (існуючий)
        # --- CONVERSATION HANDLERS ---

        # CONVERSATION: СКАРГИ (існуючий)
        complaint_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(complaint_start_simplified, pattern="^complaint$", block=False)],
            states={
                States.COMPLAINT_AWAIT_TEXT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_save_simplified),
                    # Обробка кнопок "Скасувати" та "Головне меню"
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
            },
            fallbacks=[
                CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                CallbackQueryHandler(main_menu, pattern="^main_menu$")
            ]
        )


        # CONVERSATION: ПОДЯКИ (ОНОВЛЕНО)
        thanks_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(thanks_start, pattern="^thanks$", block=False)],
            states={
                States.THANKS_PROBLEM: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, thanks_ask_specific),
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.THANKS_ASK_SPECIFIC: [
                    CallbackQueryHandler(thanks_get_route, pattern="^thanks_specific:yes$"),
                    CallbackQueryHandler(thanks_ask_name, pattern="^thanks_specific:no$"),
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.THANKS_ROUTE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, thanks_get_board),
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.THANKS_BOARD: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, thanks_ask_name),
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.THANKS_ASK_NAME: [
                    CallbackQueryHandler(thanks_get_name, pattern="^thanks_name:yes$"),
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.THANKS_GET_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, thanks_save),  # Зберегти з ім'ям
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
            },
            fallbacks=[
                CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                CallbackQueryHandler(main_menu, pattern="^main_menu$")
            ]
        )

        # NEW CONVERSATION: ПРОПОЗИЦІЇ (Оновлено)
        suggestion_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(suggestion_start, pattern="^suggestion$", block=False)],
            states={
                States.SUGGESTION_TEXT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, suggestion_ask_contact),
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.SUGGESTION_GET_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, suggestion_get_phone),
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.SUGGESTION_GET_PHONE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, suggestion_get_email),  # <-- ЗМІНЕНО
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                # --- ДОДАЙТЕ ЦЕЙ БЛОК ---
                States.SUGGESTION_EMAIL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, suggestion_save_with_email),
                    # Додаємо обробник для кнопки "Пропустити"
                    CallbackQueryHandler(suggestion_save_skip_email, pattern="^suggestion_skip_email$"),
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                # --- КІНЕЦЬ ДОДАВАННЯ ---
            },
            fallbacks=[
                CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                CallbackQueryHandler(main_menu, pattern="^main_menu$")
            ]
        )

        # NEW CONVERSATION: РЕЄСТРАЦІЯ В МУЗЕЙ
        museum_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(museum_register_start, pattern="^museum:register_start$")],
            states={
                States.MUSEUM_DATE: [
                    CallbackQueryHandler(museum_get_date, pattern="^museum_date:"),
                    # Додаємо fallback прямо у стан
                    CallbackQueryHandler(show_museum_menu, pattern="^museum_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.MUSEUM_PEOPLE_COUNT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, museum_get_people_count),
                    # КРИТИЧНО: Додаємо обробку кнопок!
                    CallbackQueryHandler(show_museum_menu, pattern="^museum_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.MUSEUM_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, museum_get_name),
                    # КРИТИЧНО: Додаємо обробку кнопок!
                    CallbackQueryHandler(show_museum_menu, pattern="^museum_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.MUSEUM_PHONE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, museum_get_phone_and_save),
                    # КРИТИЧНО: Додаємо обробку кнопок!
                    CallbackQueryHandler(show_museum_menu, pattern="^museum_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
            },
            fallbacks=[
                CallbackQueryHandler(show_museum_menu, pattern="^museum_menu$"),
                CallbackQueryHandler(main_menu, pattern="^main_menu$")
            ]
        )
        # NEW CONVERSATION: АДМІН-ПАНЕЛЬ МУЗЕЮ
        admin_conv = ConversationHandler(
            entry_points=[
                CommandHandler("admin_museum", admin_menu),  # Додаткова команда
                CallbackQueryHandler(admin_add_date_start, pattern="^admin_add_date$"),
                CallbackQueryHandler(admin_del_date_menu, pattern="^admin_del_date_menu$"),
                CallbackQueryHandler(admin_menu_show, pattern="^admin_menu_show$")
            ],
            states={
                States.ADMIN_STATE_ADD_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_date_save)],
                States.ADMIN_STATE_DEL_DATE_CONFIRM: [
                    CallbackQueryHandler(admin_del_date_confirm, pattern="^admin_del_confirm:")]
            },
            fallbacks=[
                CommandHandler("admin_museum", admin_menu),
                CallbackQueryHandler(admin_menu_show, pattern="^admin_menu_show$")
            ],
            block=False
        )
        # --- 3. ДОДАЄМО НАШ НОВИЙ CONVERSATION HANDLER ---
        accessible_conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(accessible_start, pattern="^accessible_start$")
            ],
            states={
                States.ACCESSIBLE_CHOOSE_ROUTE: [
                    CallbackQueryHandler(accessible_show_routes, pattern="^acc_type:"),
                    CallbackQueryHandler(accessible_start, pattern="^accessible_start$")
                ],

                # --- НОВА, СПРОЩЕНКА ЛОГІКА ---
                States.ACCESSIBLE_GET_LOCATION: [
                    # Сюди ми потрапляємо, обравши маршрут (accessible_show_routes)
                    # АБО з кнопки "Надати геолокацію"
                    CallbackQueryHandler(accessible_request_location, pattern="^acc_route:"),

                    # Цей обробник "ловить" саму геолокацію
                    MessageHandler(filters.LOCATION, accessible_process_stub),
                ],
                # --- КІНЕЦЬ НОВОЇ ЛОГІКИ ---

                States.ACCESSIBLE_AWAIT_NOTIFY: [
                    CallbackQueryHandler(accessible_notify_me, pattern="^acc_notify_me$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$"),
                ],
            },
            fallbacks=[
                CallbackQueryHandler(main_menu, pattern="^main_menu$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, accessible_text_cancel)
            ],
            block=False
        )
        # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

        # Додавання всіх conversation handlers
        self.app.add_handler(complaint_conv)
        self.app.add_handler(thanks_conv)
        self.app.add_handler(suggestion_conv)
        self.app.add_handler(museum_conv)
        self.app.add_handler(admin_conv)
        self.app.add_handler(accessible_conv)

        logger.info("✅ All handlers configured")

        # --- ГОЛОВНЕ МЕНЮ ---
        self.app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))

        # --- ОБРОБНИКИ МЕНЮ 1-ГО РІВНЯ ---
        self.app.add_handler(CallbackQueryHandler(realtime_transport, pattern="^realtime_transport$"))
        self.app.add_handler(CallbackQueryHandler(show_tickets_menu, pattern="^tickets_menu$"))
        self.app.add_handler(CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"))
        self.app.add_handler(CallbackQueryHandler(show_info_menu, pattern="^info_menu$"))
        self.app.add_handler(CallbackQueryHandler(show_museum_menu, pattern="^museum_menu$"))
        self.app.add_handler(CallbackQueryHandler(show_company_menu, pattern="^company_menu$"))
        self.app.add_handler(CallbackQueryHandler(show_vacancies_menu, pattern="^vacancies_menu$"))
        self.app.add_handler(CallbackQueryHandler(show_education_menu, pattern="^education_menu$"))

        # --- ОБРОБНИКИ 2-ГО+ РІВНЯ (РОУТЕРИ) ---
        self.app.add_handler(CallbackQueryHandler(show_passes_list, pattern="^tickets:passes$"))
        self.app.add_handler(CallbackQueryHandler(handle_ticket_static, pattern="^tickets:"))
        self.app.add_handler(CallbackQueryHandler(send_rules_pdf, pattern="^info:rules$"))
        self.app.add_handler(CallbackQueryHandler(handle_info_static, pattern="^info:"))
        self.app.add_handler(CallbackQueryHandler(admin_show_bookings, pattern="^admin_show_bookings$"))
        # --- ПОЧАТОК ЗМІН (Музей) --- 03/11/2025
        # 1. Новий обробник для "Інфо" (фото + текст)
        self.app.add_handler(CallbackQueryHandler(show_museum_info, pattern="^museum:info$"))
        # 2. Старий обробник тепер ТІЛЬКИ для "Соц. мережі"
        self.app.add_handler(CallbackQueryHandler(handle_museum_static,
                                                  pattern="^museum:socials$"))
        # (Обробник "museum:register_start" вже є у ConversationHandler,
        #  тому ці патерни більше не конфліктують)
        # --- КІНЕЦЬ ЗМІН ---

        # Обробники "Про підприємство" (складніші)
        self.app.add_handler(CallbackQueryHandler(show_history_menu, pattern="^company:history$"))
        self.app.add_handler(CallbackQueryHandler(show_services_menu, pattern="^company:services$"))
        self.app.add_handler(CallbackQueryHandler(handle_company_static, pattern="^company:socials$"))
        self.app.add_handler(CallbackQueryHandler(show_vacancy_list, pattern="^vacancy_type:"))


        # Обробник "Загублені речі"
        self.app.add_handler(CallbackQueryHandler(lost_items, pattern="^lost_items$"))



    async def start(self):
        logger.info("🚀 Starting bot polling...")
        await self.app.run_polling()

    #async def stop(self):
       # """Зупинка бота"""
        # ... (код без змін) ...