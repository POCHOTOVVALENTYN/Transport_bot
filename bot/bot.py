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
    accessible_search_stop,
    accessible_stop_quick_search,
    accessible_stop_selected,
    accessible_text_cancel,
    load_easyway_route_ids, accessible_back_to_list, accessible_retry_manual_search  # <-- НОВИЙ ВАЖЛИВИЙ ІМПОРТ
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
    thanks_start, thanks_text, thanks_route, thanks_board,
    thanks_name, skip_route, skip_board, thanks_cancel, register_thanks_handlers
)

from handlers.suggestion_handlers import (
    suggestion_start, suggestion_ask_contact, suggestion_get_name,
    suggestion_get_phone, suggestion_get_email, suggestion_save_with_email,
    suggestion_save_skip_email # <-- 'suggestion_save_anonymously' видалено
)


from handlers.admin_handlers import (
    admin_menu, admin_add_date_start, admin_add_date_save,
    admin_del_date_menu, admin_del_date_confirm, admin_menu_show,
    admin_show_bookings, admin_sync_db,
    admin_broadcast_start, admin_broadcast_preview,       # Нова функція прев'ю
    admin_broadcast_send_confirm,
    show_general_admin_menu, admin_museum_menu_show # Нова функція зі списком
)

from utils.logger import logger

from handlers.subscription_handlers import show_subscription_menu, handle_subscription_choice
from handlers.common import dismiss_broadcast_message

from handlers.common import handle_unexpected_message


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

        admin_conv = ConversationHandler(
            entry_points=[
                CommandHandler("admin_museum", admin_menu),
                # ВХІД ЧЕРЕЗ НОВИЙ CALLBACK
                CallbackQueryHandler(admin_museum_menu_show, pattern="^admin_museum_menu$"),

                # Кнопки дій теж є точками входу
                CallbackQueryHandler(admin_add_date_start, pattern="^admin_add_date$"),
                CallbackQueryHandler(admin_del_date_menu, pattern="^admin_del_date_menu$"),
                # === 👇 (1) ДОДАЄМО ВХІД ДЛЯ РОЗСИЛКИ ТУТ 👇 ===
                CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast_start$"),

            ],
            states={
                States.ADMIN_STATE_ADD_DATE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_date_save),
                    # Кнопка Назад
                    CallbackQueryHandler(admin_museum_menu_show, pattern="^admin_museum_menu$")
                ],
                States.ADMIN_STATE_DEL_DATE_CONFIRM: [
                    CallbackQueryHandler(admin_del_date_confirm, pattern="^admin_del_confirm:"),
                    CallbackQueryHandler(admin_museum_menu_show, pattern="^admin_museum_menu$")
                ],
                # === 👇 (2) ДОДАЄМО СТАНИ РОЗСИЛКИ ТУТ 👇 ===
                States.ADMIN_BROADCAST_TEXT: [
                    MessageHandler(filters.ALL & ~filters.COMMAND, admin_broadcast_preview)
                ],
                States.ADMIN_BROADCAST_CONFIRM: [
                    CallbackQueryHandler(admin_broadcast_send_confirm, pattern="^broadcast_confirm$"),
                    CallbackQueryHandler(admin_broadcast_send_confirm, pattern="^broadcast_cancel$"),
                ]
                # =============================================
            },
            fallbacks=[
                CallbackQueryHandler(admin_museum_menu_show, pattern="^admin_museum_menu$"),
                CommandHandler("admin_museum", admin_menu),

                # === 👇 (3) ДОДАЄМО ВИХІД В ЗАГАЛЬНУ АДМІНКУ ТУТ 👇 ===
                # Це потрібно, щоб кнопка "Скасувати" (яка веде в general_admin_menu) спрацювала як вихід з діалогу
                CallbackQueryHandler(show_general_admin_menu, pattern="^general_admin_menu$")
            ],
            allow_reentry=True
        )

        self.app.add_handler(admin_conv)

        # І додаємо хендлер для показу меню (якщо ми не в діалозі)
        self.app.add_handler(CallbackQueryHandler(admin_museum_menu_show, pattern="^admin_museum_menu$"))
        # --- СПОВІЩЕННЯ ---
        self.app.add_handler(CallbackQueryHandler(show_subscription_menu, pattern="^subscription_menu$"))
        self.app.add_handler(CallbackQueryHandler(handle_subscription_choice, pattern="^sub:"))

        # --- ОБРОБКА КНОПКИ "ПРИХОВАТИ" (ПІД РОЗСИЛКОЮ) ---
        self.app.add_handler(CallbackQueryHandler(dismiss_broadcast_message, pattern="^broadcast_dismiss$"))

        # Кнопка входу в Адмінку Новин (Валентин/Тетяна)
        self.app.add_handler(CallbackQueryHandler(show_general_admin_menu, pattern="^general_admin_menu$"))

        # Кнопка синхронізації БД (Валентин/Тетяна)
        self.app.add_handler(CallbackQueryHandler(admin_sync_db, pattern="^admin_sync_db$"))

        # Кнопка входу в Адмінку Музею (Максим)
        self.app.add_handler(CallbackQueryHandler(admin_menu_show, pattern="^admin_menu_show$"))


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

        # CONVERSATION: ПОДЯКИ (ОНОВЛЕНО ПІД НОВУ ЛОГІКУ)
        thanks_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(thanks_start, pattern="^thanks$", block=False)],
            states={
                # 1. Чекаємо текст подяки
                States.THANKS_TEXT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, thanks_text),
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                # 2. Чекаємо маршрут (або пропуск)
                States.THANKS_ROUTE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, thanks_route),
                    CallbackQueryHandler(skip_route, pattern="^skip_route$"),  # Кнопка "Не знаю"
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                # 3. Чекаємо бортовий номер (або пропуск)
                States.THANKS_BOARD: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, thanks_board),
                    CallbackQueryHandler(skip_board, pattern="^skip_board$"),  # Кнопка "Не знаю"
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                # 4. Чекаємо ім'я (фінал)
                States.THANKS_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, thanks_name),
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
            },
            fallbacks=[
                CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                CallbackQueryHandler(main_menu, pattern="^main_menu$"),
                CommandHandler("cancel", thanks_cancel)  # Можна додати команду скасування
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


        accessible_conv = ConversationHandler(
            entry_points=[
                # Вхід через кнопку "♿ Пошук інклюзивного транспорту" [cite: 16-17]
                CallbackQueryHandler(accessible_start, pattern="^accessible_start$")
            ],
            states={
                # Крок 1: Очікування тексту (назви зупинки) або кнопки "Популярне"
                States.ACCESSIBLE_SEARCH_STOP: [
                    # Обробник тексту
                    MessageHandler(filters.TEXT & ~filters.COMMAND, accessible_search_stop),
                    # Обробник кнопок "Популярне" (напр. stop_search_Центр) [cite: 1616-1620]
                    CallbackQueryHandler(accessible_stop_quick_search, pattern="^stop_search_"),
                    # Обробник кнопки (якщо ID зупинки вже відомий, напр. "Ринок Привоз") [cite: 1622-1625]
                    CallbackQueryHandler(accessible_stop_selected, pattern="^stop_[0-9]+$"),
                    # У states -> ACCESSIBLE_SEARCH_STOP (або де ви показуєте помилку)
                    CallbackQueryHandler(accessible_retry_manual_search, pattern="^accessible_retry_manual$"),
                ],

                # Крок 2: Очікування вибору конкретної зупинки зі списку
                States.ACCESSIBLE_SELECT_STOP: [
                    # Користувач натискає кнопку "📍 ... (ID: 123)"
                    CallbackQueryHandler(accessible_stop_selected, pattern="^stop_[0-9]+$"),
                    # 2. ДОДАНО: Якщо користувач пише текст (шукає нову зупинку),
                    # ми повертаємо його на логіку пошуку.
                    MessageHandler(filters.TEXT & ~filters.COMMAND, accessible_search_stop),
                    # Додаємо кнопку "Назад" до пошуку
                    CallbackQueryHandler(accessible_start, pattern="^accessible_start$")
                ],
                # НОВИЙ КОД (ПРАВИЛЬНИЙ):
                States.ACCESSIBLE_SHOWING_RESULTS: [
                    # ✅ НОВИЙ РЯДОК: Обробник для кнопки "Оновити"
                    # Це дозволяє перезавантажити дані зупинки
                    CallbackQueryHandler(accessible_stop_selected, pattern="^stop_[0-9]+$"),

                    # Обробник для нашої нової кнопки "Назад до списку"
                    CallbackQueryHandler(accessible_back_to_list, pattern="^accessible_back_to_list$"),

                    # Обробники для кнопок "Пошук іншої" та "Головне меню"
                    CallbackQueryHandler(accessible_start, pattern="^accessible_start$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$"),

                    # новий пошук одразу з результатів
                    MessageHandler(filters.TEXT & ~filters.COMMAND, accessible_search_stop),
                ],
            },
            fallbacks=[
                CallbackQueryHandler(main_menu, pattern="^main_menu$"),
                CallbackQueryHandler(accessible_start, pattern="^accessible_start$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, accessible_text_cancel)
            ],
            block=False
        )

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

        # === 👇 ГЛОБАЛЬНИЙ ПЕРЕХОПЛЮВАЧ (Anti-Spam / Cleaner) 👇 ===
        # Він спрацює ТІЛЬКИ якщо жоден інший хендлер вище не зреагував.
        # filters.ALL & ~filters.COMMAND означає "Все (текст, фото, відео), крім команд (/start)"
        self.app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_unexpected_message))



    async def start(self):
        logger.info("🚀 Starting bot polling...")
        await self.app.run_polling()

    #async def stop(self):
       # """Зупинка бота"""
        # ... (код без змін) ...