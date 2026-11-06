# bot/bot.py

from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler
)

# --- Старі імпорти ---
from handlers.command_handlers import cmd_start, cmd_help
from handlers.complaint_handlers import (
    complaint_start_simplified, complaint_choose_type_step,
    complaint_transport_type_step,
    complaint_route_step, complaint_board_step, complaint_text_step,
    complaint_name_step, complaint_phone_step, complaint_email_step,
    complaint_edit_menu, complaint_edit_field_handler, complaint_edit_back,
    complaint_save_final, complaint_response_need_step, complaint_home_address_step
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
    realtime_transport
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
    show_vacancy_list, vacancy_show_phone, show_education_menu, show_services_menu,
    show_history_menu
)
from handlers.museum_handlers import (
    show_museum_menu, handle_museum_static, museum_register_start,
    museum_get_date, museum_get_people_count, museum_get_name,
    museum_get_phone_input, show_museum_info, museum_show_confirm,
    museum_edit_choice, museum_edit_field, museum_confirm_save,
    museum_get_participant_name, museum_get_participant_age
)

from handlers.thanks_handlers import (
    thanks_start, thanks_specific_type_selection, thanks_transport_selected,
    thanks_board_number_input, thanks_skip_board, thanks_reason_input,
    thanks_phone_step, thanks_general_start, thanks_general_message,
    thanks_general_name, register_thanks_handlers,
    thanks_input_email_and_confirm, thanks_confirm_save
)

from handlers.suggestion_handlers import (
    suggestion_start, suggestion_ask_contact, suggestion_get_name,
    suggestion_get_phone, suggestion_check_data, suggestion_save_final,
    suggestion_response_need_step, suggestion_home_address_step
)


from handlers.admin_handlers import (
    admin_menu, admin_add_date_start, admin_add_date_save,
    admin_add_date_capacity_save,
    admin_del_date_menu, admin_del_date_confirm, admin_menu_show,
    admin_show_bookings, admin_sync_db,
    admin_broadcast_start, admin_broadcast_preview,
    admin_broadcast_duration_selected,
    admin_broadcast_send_confirm,
    show_general_admin_menu, admin_museum_menu_show, admin_show_stats, # Нова функція зі списком
    admin_add_holiday_date_start, admin_add_holiday_date_save,
    admin_add_holiday_date_capacity_save,
    admin_del_holiday_date_menu, admin_del_holiday_date_confirm,
    admin_show_holiday_bookings, admin_export_users,
    admin_export_doc_select, admin_export_doc_generate,
    moderate_approve_callback, moderate_reject_callback,
    admin_mail_archive_menu, admin_mail_show_category,
    admin_mail_show_detail, admin_mail_resend,
    admin_news_archive, admin_news_detail, admin_news_toggle,
    admin_lost_menu, admin_lost_list, admin_lost_view,
    admin_lost_return, admin_lost_delete, admin_lost_archive,
    admin_lost_add_start, admin_lost_cat_selected,
    admin_lost_title_input, admin_lost_details_input,
    admin_lost_skip_details, admin_lost_cancel,
    admin_lost_edit_start, admin_lost_edit_choice_selected,
    admin_lost_edit_title_input, admin_lost_edit_details_input,
    admin_lost_edit_cancel,
    admin_vacancy_menu, admin_vacancy_list, admin_vacancy_view,
    admin_vacancy_deactivate, admin_vacancy_add_start,
    admin_vacancy_cat_selected, admin_vacancy_title_input,
    admin_vacancy_contact_type_selected, admin_vacancy_contact_value_input,
    admin_vacancy_cancel,
    admin_vacancy_edit_start, admin_vacancy_edit_choice_selected,
    admin_vacancy_edit_set_contact_type, admin_vacancy_edit_title_input,
    admin_vacancy_edit_contact_value_input, admin_vacancy_edit_cancel
)
from handlers.news_handlers import news_client_list, news_client_view
from handlers.lost_items_handlers import show_lost_items_menu, show_lost_items_category
from handlers.rental_client_handlers import (
    handle_client_pick_order_slot,
    handle_rental_redownload_pdfs,
    rental_finalize_order,
    rental_handle_customer_type_selected,
    rental_handle_custom_time_input,
    rental_handle_date_button,
    rental_handle_date_text,
    rental_handle_delete_file,
    rental_handle_dropoff_loop_selected,
    rental_handle_loop_pagination,
    rental_handle_name_input,
    rental_handle_phone_input,
    rental_handle_pickup_loop_selected,
    rental_handle_resend_docs,
    rental_handle_safety_accepted,
    rental_handle_signing_selected,
    rental_handle_slot_selected,
    rental_handle_stop_hub_callback,
    rental_handle_stop_search_input,
    rental_handle_stop_selected,
    rental_handle_tax_input,
    rental_handle_via_clear,
    rental_handle_via_done,
    rental_handle_via_loop_selected,
    rental_handle_wait_selected,
    rental_prompt_signing_scenario,
    rental_receive_uploaded_document,
    rental_select_preset,
    rental_select_route_mode,
    rental_select_wagon,
    rental_start_upload_document,
    rental_start_wizard,
    rental_toggle_extra,
    show_my_rental_contracts,
    show_rental_contract_detail,
    show_rental_hub,
    show_rental_rules_info,
    _prompt_route_mode,
    _render_customer_name_input,
    _render_customer_phone_input,
    _render_customer_type_selection,
    _render_date_selection,
    _render_safety_briefing,
    _render_slot_selection,
    _render_stop_selection_hub,
    _render_wialon_calculation_and_extras,
)
from handlers.rental_staff_handlers import (
    check_rental_timeouts_job,
    cmd_add_rental_role,
    cmd_analytics_panel,
    cmd_bind_topic,
    cmd_chatid,
    cmd_depot_slots_panel,
    cmd_set_rental_chat,
    cmd_topics_status,
    handle_analytics_callback,
    handle_depot_slots_callback,
    handle_rental_staff_callback,
    handle_staff_group_text_input,
)

from utils.logger import logger
from config.settings import FEEDBACK_SYNC_INTERVAL_MIN
from services.tickets_service import TicketsService
from services.news_service import NewsService

from handlers.common import dismiss_broadcast_message, delete_message_callback

from handlers.common import handle_unexpected_message


class TransportBot:
    """Головний клас бота"""

    def __init__(self, token: str):
        self.token = token
        self.tickets_service = TicketsService()
        self.news_service = NewsService()

        # 1. ЗАЛИШАЄМО ТІЛЬКИ ОДИН РЯДОК Application.builder
        #    з реєстрацією `post_init`.
        self.app = Application.builder().token(token).build()

        # Рядок (self.app = Application.builder().token(token).build()) ВИДАЛЕНО

        self._setup_handlers()
        self._setup_jobs()

    def _setup_jobs(self):
        if not self.app.job_queue:
            logger.warning("⚠️ JobQueue is not configured. Auto-sync is disabled.")
            return
        interval_minutes = max(5, FEEDBACK_SYNC_INTERVAL_MIN)
        interval_seconds = interval_minutes * 60
        self.app.job_queue.run_repeating(
            self._auto_sync_feedbacks,
            interval=interval_seconds,
            first=interval_seconds,
            name="auto_sync_feedbacks"
        )
        news_check_seconds = 30 * 60
        self.app.job_queue.run_repeating(
            self._auto_expire_news,
            interval=news_check_seconds,
            first=news_check_seconds,
            name="auto_expire_news"
        )
        rental_timeout_seconds = 15 * 60
        self.app.job_queue.run_repeating(
            check_rental_timeouts_job,
            interval=rental_timeout_seconds,
            first=120,
            name="check_rental_timeouts_job",
        )

    async def _auto_sync_feedbacks(self, context):
        try:
            count = await self.tickets_service.sync_new_feedbacks_to_sheets()
            if count:
                logger.info(f"✅ Auto-sync: synced {count} feedback(s) to Sheets")
        except Exception as e:
            logger.error(f"❌ Auto-sync failed: {e}")

    async def _auto_expire_news(self, context):
        try:
            count = await self.news_service.deactivate_expired_news()
            if count:
                logger.info(f"✅ Auto-expire: deactivated {count} news item(s) past their expiry")
        except Exception as e:
            logger.error(f"❌ Auto-expire news failed: {e}")


    def _setup_handlers(self):
        """Налаштування всіх обробників"""
        logger.info("🔧 Setting up handlers...")

        # --- КОМАНДИ ---
        self.app.add_handler(CommandHandler("start", cmd_start))
        self.app.add_handler(CommandHandler("help", cmd_help))
        self.app.add_handler(CommandHandler("chatid", cmd_chatid))
        self.app.add_handler(CommandHandler("set_rental_chat", cmd_set_rental_chat))
        self.app.add_handler(CommandHandler("add_rental_role", cmd_add_rental_role))
        self.app.add_handler(CommandHandler("bind_topic", cmd_bind_topic))
        self.app.add_handler(CommandHandler("topics_status", cmd_topics_status))
        self.app.add_handler(CommandHandler("depot_slots", cmd_depot_slots_panel))
        self.app.add_handler(CommandHandler("analytics", cmd_analytics_panel))

        admin_conv = ConversationHandler(
            entry_points=[
                CommandHandler("admin_museum", admin_menu),
                # ВХІД ЧЕРЕЗ НОВИЙ CALLBACK
                CallbackQueryHandler(admin_museum_menu_show, pattern="^admin_museum_menu$"),

                # Кнопки дій теж є точками входу
                CallbackQueryHandler(admin_add_date_start, pattern="^admin_add_date$"),
                CallbackQueryHandler(admin_del_date_menu, pattern="^admin_del_date_menu$"),
                CallbackQueryHandler(admin_add_holiday_date_start, pattern="^admin_add_holiday_date$"),
                CallbackQueryHandler(admin_del_holiday_date_menu, pattern="^admin_del_holiday_date_menu$"),
                # === 👇 (1) ДОДАЄМО ВХІД ДЛЯ РОЗСИЛКИ ТУТ 👇 ===
                CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast_start$"),

            ],
            states={
                States.ADMIN_STATE_ADD_DATE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_date_save),
                    # Кнопка Назад
                    CallbackQueryHandler(admin_museum_menu_show, pattern="^admin_museum_menu$")
                ],
                States.ADMIN_STATE_ADD_DATE_CAPACITY: [
                    CallbackQueryHandler(admin_add_date_capacity_save, pattern="^admin_date_cap:"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_date_capacity_save),
                    CallbackQueryHandler(admin_museum_menu_show, pattern="^admin_museum_menu$")
                ],
                States.ADMIN_STATE_DEL_DATE_CONFIRM: [
                    CallbackQueryHandler(admin_del_date_confirm, pattern="^admin_del_confirm:"),
                    CallbackQueryHandler(admin_museum_menu_show, pattern="^admin_museum_menu$")
                ],
                States.ADMIN_STATE_ADD_HOLIDAY_DATE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_holiday_date_save),
                    CallbackQueryHandler(admin_museum_menu_show, pattern="^admin_museum_menu$")
                ],
                States.ADMIN_STATE_ADD_HOLIDAY_DATE_CAPACITY: [
                    CallbackQueryHandler(admin_add_holiday_date_capacity_save, pattern="^admin_holiday_cap:"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_holiday_date_capacity_save),
                    CallbackQueryHandler(admin_museum_menu_show, pattern="^admin_museum_menu$")
                ],
                States.ADMIN_STATE_DEL_HOLIDAY_DATE_CONFIRM: [
                    CallbackQueryHandler(admin_del_holiday_date_confirm, pattern="^admin_del_holiday_confirm:"),
                    CallbackQueryHandler(admin_museum_menu_show, pattern="^admin_museum_menu$")
                ],
                # === 👇 (2) ДОДАЄМО СТАНИ РОЗСИЛКИ ТУТ 👇 ===
                States.ADMIN_BROADCAST_TEXT: [
                    MessageHandler(filters.ALL & ~filters.COMMAND, admin_broadcast_preview)
                ],
                States.ADMIN_BROADCAST_DURATION: [
                    CallbackQueryHandler(admin_broadcast_duration_selected, pattern="^admin_broadcast_set_duration:"),
                    CallbackQueryHandler(admin_broadcast_send_confirm, pattern="^broadcast_cancel$"),
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

                # === 👇 (3) ДОДАЄМО ВИХІД В ЗАГАЛЬНУ АДМІНКУ ТА ГОЛОВНЕ МЕНЮ ТУТ 👇 ===
                CallbackQueryHandler(show_general_admin_menu, pattern="^general_admin_menu$"),
                CallbackQueryHandler(main_menu, pattern="^main_menu$")
            ],
            allow_reentry=True
        )

        self.app.add_handler(admin_conv)

        # І додаємо хендлер для показу меню (якщо ми не в діалозі)
        self.app.add_handler(CallbackQueryHandler(admin_museum_menu_show, pattern="^admin_museum_menu$"))
        # --- ОБРОБКА КНОПКИ "ПРИХОВАТИ" (ПІД РОЗСИЛКОЮ ТА СПОВІЩЕННЯМИ) ---
        self.app.add_handler(CallbackQueryHandler(dismiss_broadcast_message, pattern="^broadcast_dismiss$"))
        self.app.add_handler(CallbackQueryHandler(delete_message_callback, pattern="^delete_message$"))

        # Кнопка входу в Адмінку Новин (Валентин/Тетяна)
        self.app.add_handler(CallbackQueryHandler(show_general_admin_menu, pattern="^general_admin_menu$"))

        # Кнопка синхронізації БД (Валентин/Тетяна)
        self.app.add_handler(CallbackQueryHandler(admin_sync_db, pattern="^admin_sync_db$"))

        # Кнопка статистики (Валентин/Тетяна)
        self.app.add_handler(CallbackQueryHandler(admin_show_stats, pattern="^admin_stats$"))
        self.app.add_handler(CallbackQueryHandler(admin_export_users, pattern="^admin_export_users$"))

        # Модерація звернень (Затвердити / Відхилити)
        self.app.add_handler(CallbackQueryHandler(moderate_approve_callback, pattern="^feed_mod:approve:"))
        self.app.add_handler(CallbackQueryHandler(moderate_reject_callback, pattern="^feed_mod:reject:"))

        # Поштовий архів звернень для загальних адмінів
        self.app.add_handler(CallbackQueryHandler(admin_mail_archive_menu, pattern="^admin_mail_archive$"))
        self.app.add_handler(CallbackQueryHandler(admin_mail_show_category, pattern="^admin_mail_cat:"))
        self.app.add_handler(CallbackQueryHandler(admin_mail_show_detail, pattern="^admin_mail_detail:"))
        self.app.add_handler(CallbackQueryHandler(admin_mail_resend, pattern="^admin_mail_resend:"))

        # Архів оперативних новин та розсилок для загальних адмінів
        self.app.add_handler(CallbackQueryHandler(admin_news_archive, pattern="^admin_news_archive(:.*)?$"))
        self.app.add_handler(CallbackQueryHandler(admin_news_detail, pattern="^admin_news_view(:.*)?$"))
        self.app.add_handler(CallbackQueryHandler(admin_news_toggle, pattern="^admin_news_toggle(:.*)?$"))

        # Керування загубленими речами для загальних адмінів
        admin_lost_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_lost_add_start, pattern="^admin_lost_add_start$")],
            states={
                States.ADMIN_LOST_CATEGORY: [
                    CallbackQueryHandler(admin_lost_cat_selected, pattern="^admin_lost_set_cat:")
                ],
                States.ADMIN_LOST_TITLE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_lost_title_input)
                ],
                States.ADMIN_LOST_DETAILS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_lost_details_input),
                    CallbackQueryHandler(admin_lost_skip_details, pattern="^admin_lost_skip_details$")
                ]
            },
            fallbacks=[
                CallbackQueryHandler(admin_lost_cancel, pattern="^admin_lost_cancel$"),
                CallbackQueryHandler(main_menu, pattern="^main_menu$")
            ],
            block=False
        )
        self.app.add_handler(admin_lost_conv)

        self.app.add_handler(CallbackQueryHandler(admin_lost_menu, pattern="^admin_lost_menu$"))
        self.app.add_handler(CallbackQueryHandler(admin_lost_list, pattern="^admin_lost_list:"))
        self.app.add_handler(CallbackQueryHandler(admin_lost_view, pattern="^admin_lost_view:"))
        self.app.add_handler(CallbackQueryHandler(admin_lost_return, pattern="^admin_lost_return:"))
        self.app.add_handler(CallbackQueryHandler(admin_lost_delete, pattern="^admin_lost_delete:"))
        self.app.add_handler(CallbackQueryHandler(admin_lost_archive, pattern="^admin_lost_archive(:.*)?$"))

        # Редагування вже створеної знахідки
        admin_lost_edit_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_lost_edit_start, pattern="^admin_lost_edit_start:")],
            states={
                States.ADMIN_LOST_EDIT_CHOICE: [
                    CallbackQueryHandler(admin_lost_edit_choice_selected, pattern="^admin_lost_edit_choice:")
                ],
                States.ADMIN_LOST_EDIT_TITLE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_lost_edit_title_input)
                ],
                States.ADMIN_LOST_EDIT_DETAILS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_lost_edit_details_input)
                ]
            },
            fallbacks=[
                CallbackQueryHandler(admin_lost_edit_cancel, pattern="^admin_lost_edit_cancel$"),
                CallbackQueryHandler(main_menu, pattern="^main_menu$")
            ],
            block=False
        )
        self.app.add_handler(admin_lost_edit_conv)

        # Керування вакансіями для загальних адмінів
        admin_vacancy_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_vacancy_add_start, pattern="^admin_vacancy_add_start$")],
            states={
                States.ADMIN_VACANCY_CATEGORY: [
                    CallbackQueryHandler(admin_vacancy_cat_selected, pattern="^admin_vacancy_set_cat:")
                ],
                States.ADMIN_VACANCY_TITLE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_vacancy_title_input)
                ],
                States.ADMIN_VACANCY_CONTACT_TYPE: [
                    CallbackQueryHandler(admin_vacancy_contact_type_selected, pattern="^admin_vacancy_set_contact_type:")
                ],
                States.ADMIN_VACANCY_CONTACT_VALUE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_vacancy_contact_value_input)
                ]
            },
            fallbacks=[
                CallbackQueryHandler(admin_vacancy_cancel, pattern="^admin_vacancy_cancel$"),
                CallbackQueryHandler(main_menu, pattern="^main_menu$")
            ],
            block=False
        )
        self.app.add_handler(admin_vacancy_conv)

        # Редагування вже створеної вакансії
        admin_vacancy_edit_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_vacancy_edit_start, pattern="^admin_vacancy_edit_start:")],
            states={
                States.ADMIN_VACANCY_EDIT_CHOICE: [
                    CallbackQueryHandler(admin_vacancy_edit_choice_selected, pattern="^admin_vacancy_edit_choice:")
                ],
                States.ADMIN_VACANCY_EDIT_TITLE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_vacancy_edit_title_input)
                ],
                States.ADMIN_VACANCY_EDIT_CONTACT_TYPE: [
                    CallbackQueryHandler(admin_vacancy_edit_set_contact_type, pattern="^admin_vacancy_edit_set_contact_type:")
                ],
                States.ADMIN_VACANCY_EDIT_CONTACT_VALUE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_vacancy_edit_contact_value_input)
                ]
            },
            fallbacks=[
                CallbackQueryHandler(admin_vacancy_edit_cancel, pattern="^admin_vacancy_edit_cancel$"),
                CallbackQueryHandler(main_menu, pattern="^main_menu$")
            ],
            block=False
        )
        self.app.add_handler(admin_vacancy_edit_conv)

        self.app.add_handler(CallbackQueryHandler(admin_vacancy_menu, pattern="^admin_vacancy_menu$"))
        self.app.add_handler(CallbackQueryHandler(admin_vacancy_list, pattern="^admin_vacancy_list:"))
        self.app.add_handler(CallbackQueryHandler(admin_vacancy_view, pattern="^admin_vacancy_view:"))
        self.app.add_handler(CallbackQueryHandler(admin_vacancy_deactivate, pattern="^admin_vacancy_deactivate:"))

        # Кнопка входу в Адмінку Музею (Максим)
        self.app.add_handler(CallbackQueryHandler(admin_menu_show, pattern="^admin_menu_show$"))

        # CONVERSATION: СКАРГИ (Оновлений з підтвердженням)
        complaint_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(complaint_start_simplified, pattern="^complaint$", block=False)],
            states={
                States.COMPLAINT_CHOOSE_TYPE: [
                    CallbackQueryHandler(complaint_choose_type_step, pattern="^complaint_type:")
                ],
                States.COMPLAINT_TRANSPORT_TYPE: [
                    CallbackQueryHandler(complaint_transport_type_step, pattern="^complaint_transport:")
                ],
                States.COMPLAINT_ROUTE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_route_step)
                ],
                States.COMPLAINT_BOARD: [
                    CallbackQueryHandler(complaint_board_step, pattern="^complaint_skip_board$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_board_step)
                ],
                States.COMPLAINT_TEXT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_text_step)
                ],
                States.COMPLAINT_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_name_step)
                ],
                States.COMPLAINT_PHONE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_phone_step)
                ],
                States.COMPLAINT_EMAIL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_email_step)
                ],
                States.COMPLAINT_RESPONSE_NEED: [
                    CallbackQueryHandler(complaint_response_need_step, pattern="^complaint_resp:")
                ],
                States.COMPLAINT_HOME_ADDRESS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, complaint_home_address_step)
                ],
                States.COMPLAINT_CONFIRMATION: [
                    CallbackQueryHandler(complaint_save_final, pattern="^complaint_confirm_send$"),
                    CallbackQueryHandler(complaint_edit_menu, pattern="^complaint_edit_menu$"),
                    CallbackQueryHandler(complaint_start_simplified, pattern="^complaint$"),
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$")
                ],
                States.COMPLAINT_EDIT_CHOICE: [
                    CallbackQueryHandler(complaint_edit_field_handler, pattern="^complaint_edit:"),
                    CallbackQueryHandler(complaint_edit_back, pattern="^complaint_edit_back$")
                ]
            },
            fallbacks=[
                CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                CallbackQueryHandler(main_menu, pattern="^main_menu$")
            ],
            per_message=False  # Додайте це, щоб прибрати warning у логах
        )

        # 1. Імпорт функції реєстрації (нагорі файлу або перед використанням)
        from handlers.thanks_handlers import register_thanks_handlers

        # 2. Отримання конфігурації
        thanks_conf = register_thanks_handlers()

        # 3. Створення ConversationHandler
        thanks_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(ep[2], pattern=f"^{ep[1]}$") for ep in thanks_conf['entry_points']],
            states={
                state: [
                    # Якщо це message handler
                    MessageHandler(filters.TEXT & ~filters.COMMAND, h[2]) if h[0] == 'message'
                    # Якщо це callback handler (кнопка)
                    else CallbackQueryHandler(h[2], pattern=f"^{h[1]}$")
                    for h in handlers
                ]
                for state, handlers in thanks_conf['states'].items()
            },
            fallbacks=[
                CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                CallbackQueryHandler(main_menu, pattern="^main_menu$")
            ],
            per_message=False
        )

        # NEW CONVERSATION: ПРОПОЗИЦІЇ (Оновлено)
        suggestion_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(suggestion_start, pattern="^suggestion$")],
            states={
                States.SUGGESTION_TEXT: [MessageHandler(filters.TEXT, suggestion_ask_contact)],
                States.SUGGESTION_GET_NAME: [MessageHandler(filters.TEXT, suggestion_get_name)],
                States.SUGGESTION_GET_PHONE: [MessageHandler(filters.TEXT, suggestion_get_phone)],

                # На етапі Email ми тепер йдемо на перевірку (check_data)
                States.SUGGESTION_EMAIL: [
                    MessageHandler(filters.TEXT, suggestion_check_data)
                ],
                States.SUGGESTION_RESPONSE_NEED: [
                    CallbackQueryHandler(suggestion_response_need_step, pattern="^suggestion_resp:")
                ],
                States.SUGGESTION_HOME_ADDRESS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, suggestion_home_address_step)
                ],
                States.SUGGESTION_CONFIRMATION: [
                    CallbackQueryHandler(suggestion_save_final, pattern="^suggestion_confirm_send$"),
                    CallbackQueryHandler(suggestion_start, pattern="^suggestion$"),
                    CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$")
                ]
            },
            fallbacks=[
                CallbackQueryHandler(show_feedback_menu, pattern="^feedback_menu$"),
                CallbackQueryHandler(main_menu, pattern="^main_menu$")
            ],
            per_message=False
        )

        museum_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(museum_register_start, pattern="^museum:(holiday_)?register_start$")],
            states={
                States.MUSEUM_DATE: [
                    CallbackQueryHandler(museum_get_date, pattern="^museum_date:"),
                    # Додаємо fallback прямо у стан
                    CallbackQueryHandler(show_museum_menu, pattern="^museum_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.MUSEUM_PEOPLE_COUNT: [
                    CallbackQueryHandler(museum_get_people_count, pattern="^museum_count:"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, museum_get_people_count),
                    CallbackQueryHandler(show_museum_menu, pattern="^museum_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.MUSEUM_PARTICIPANT_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, museum_get_participant_name),
                    CallbackQueryHandler(show_museum_menu, pattern="^museum_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.MUSEUM_PARTICIPANT_AGE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, museum_get_participant_age),
                    CallbackQueryHandler(show_museum_menu, pattern="^museum_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.MUSEUM_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, museum_get_name),
                    CallbackQueryHandler(show_museum_menu, pattern="^museum_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.MUSEUM_PHONE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, museum_get_phone_input),
                    # КРИТИЧНО: Додаємо обробку кнопок!
                    CallbackQueryHandler(show_museum_menu, pattern="^museum_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.MUSEUM_CONFIRM: [
                    CallbackQueryHandler(museum_confirm_save, pattern="^museum_confirm_send$"),
                    CallbackQueryHandler(museum_edit_choice, pattern="^museum_edit$"),
                    CallbackQueryHandler(show_museum_menu, pattern="^museum_menu$"),
                    CallbackQueryHandler(main_menu, pattern="^main_menu$")
                ],
                States.MUSEUM_EDIT_CHOICE: [
                    CallbackQueryHandler(museum_edit_field, pattern="^museum_edit:(date|people|name|phone)$"),
                    CallbackQueryHandler(museum_show_confirm, pattern="^museum_confirm_back$"),
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

        # --- ДІАЛОГ ОФОРМЛЕННЯ ОРЕНДИ ЕЛЕКТРОТРАНСПОРТУ (WIALON) ---
        rental_conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(rental_start_wizard, pattern="^rental_start_wizard$"),
            ],
            states={
                States.RENTAL_SELECT_WAGON: [
                    CallbackQueryHandler(rental_select_wagon, pattern="^rental_wagon:"),
                    CallbackQueryHandler(show_rental_hub, pattern="^rental_hub$"),
                ],
                States.RENTAL_SELECT_ROUTE_MODE: [
                    CallbackQueryHandler(rental_select_route_mode, pattern="^rental_rmode:"),
                    CallbackQueryHandler(rental_start_wizard, pattern="^rental_start_wizard$"),
                    CallbackQueryHandler(_prompt_route_mode, pattern="^rental_back_rmode$"),
                ],
                States.RENTAL_SELECT_PRESET: [
                    CallbackQueryHandler(rental_select_preset, pattern="^rental_preset:"),
                    CallbackQueryHandler(rental_select_route_mode, pattern="^rental_rmode:"),
                    CallbackQueryHandler(_prompt_route_mode, pattern="^rental_back_rmode$"),
                ],
                States.RENTAL_SELECT_PICKUP_LOOP: [
                    CallbackQueryHandler(rental_handle_stop_selected, pattern="^rental_spick:"),
                    CallbackQueryHandler(rental_handle_stop_hub_callback, pattern="^rental_stop_"),
                    CallbackQueryHandler(rental_handle_pickup_loop_selected, pattern="^rental_loop_pick:"),
                    CallbackQueryHandler(rental_handle_loop_pagination, pattern="^rental_loop_page:"),
                    CallbackQueryHandler(_prompt_route_mode, pattern="^rental_back_rmode$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, rental_handle_stop_search_input),
                ],
                States.RENTAL_SELECT_VIA_LOOPS: [
                    CallbackQueryHandler(rental_handle_stop_selected, pattern="^rental_spick:"),
                    CallbackQueryHandler(rental_handle_stop_hub_callback, pattern="^(rental_stop_|rental_back_pickup)"),
                    CallbackQueryHandler(rental_handle_via_loop_selected, pattern="^rental_loop_via:"),
                    CallbackQueryHandler(rental_handle_loop_pagination, pattern="^rental_loop_page:"),
                    CallbackQueryHandler(rental_handle_via_clear, pattern="^rental_via_clear$"),
                    CallbackQueryHandler(rental_handle_via_done, pattern="^rental_via_done$"),
                    CallbackQueryHandler(_prompt_route_mode, pattern="^rental_back_rmode$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, rental_handle_stop_search_input),
                ],
                States.RENTAL_SELECT_DROPOFF_LOOP: [
                    CallbackQueryHandler(rental_handle_stop_selected, pattern="^rental_spick:"),
                    CallbackQueryHandler(rental_handle_stop_hub_callback, pattern="^(rental_stop_|rental_back_via)"),
                    CallbackQueryHandler(rental_handle_dropoff_loop_selected, pattern="^rental_loop_drop:"),
                    CallbackQueryHandler(rental_handle_loop_pagination, pattern="^rental_loop_page:"),
                    CallbackQueryHandler(_prompt_route_mode, pattern="^rental_back_rmode$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, rental_handle_stop_search_input),
                ],
                States.RENTAL_SEARCH_STOP_TEXT: [
                    CallbackQueryHandler(rental_handle_stop_selected, pattern="^rental_spick:"),
                    CallbackQueryHandler(rental_handle_stop_hub_callback, pattern="^rental_stop_"),
                    CallbackQueryHandler(_prompt_route_mode, pattern="^rental_back_rmode$"),
                    CallbackQueryHandler(show_rental_hub, pattern="^rental_hub$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, rental_handle_stop_search_input),
                ],
                States.RENTAL_SELECT_WAIT_TIME: [
                    CallbackQueryHandler(rental_handle_wait_selected, pattern="^rental_wait:"),
                    CallbackQueryHandler(_prompt_route_mode, pattern="^rental_back_rmode$"),
                ],
                States.RENTAL_SELECT_DATE: [
                    CallbackQueryHandler(rental_handle_date_button, pattern="^rental_date:"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, rental_handle_date_text),
                    CallbackQueryHandler(_prompt_route_mode, pattern="^rental_back_rmode$"),
                ],
                States.RENTAL_SELECT_SLOT: [
                    CallbackQueryHandler(rental_handle_slot_selected, pattern="^rental_slot:"),
                    CallbackQueryHandler(_render_date_selection, pattern="^rental_back_date$"),
                ],
                States.RENTAL_ENTER_CUSTOM_TIME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, rental_handle_custom_time_input),
                    CallbackQueryHandler(_render_slot_selection, pattern="^rental_back_slot$"),
                ],
                States.RENTAL_SELECT_EXTRAS: [
                    CallbackQueryHandler(rental_toggle_extra, pattern="^rental_extra:"),
                    CallbackQueryHandler(rental_prompt_signing_scenario, pattern="^rental_extras_done$"),
                    CallbackQueryHandler(_render_slot_selection, pattern="^rental_back_slot$"),
                ],
                States.RENTAL_SELECT_SIGNING_SCENARIO: [
                    CallbackQueryHandler(rental_handle_signing_selected, pattern="^rental_sign:"),
                    CallbackQueryHandler(_render_wialon_calculation_and_extras, pattern="^rental_back_extras$"),
                ],
                States.RENTAL_SAFETY_BRIEFING: [
                    CallbackQueryHandler(rental_handle_safety_accepted, pattern="^rental_safety_accept$"),
                    CallbackQueryHandler(show_rental_hub, pattern="^rental_hub$"),
                ],
                States.RENTAL_SELECT_CUSTOMER_TYPE: [
                    CallbackQueryHandler(rental_handle_customer_type_selected, pattern="^rental_cust_type:"),
                    CallbackQueryHandler(_render_safety_briefing, pattern="^rental_back_safety$"),
                ],
                States.RENTAL_ENTER_CUSTOMER_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, rental_handle_name_input),
                    CallbackQueryHandler(_render_customer_type_selection, pattern="^rental_back_cust_type$"),
                ],
                States.RENTAL_ENTER_CUSTOMER_PHONE: [
                    CallbackQueryHandler(_render_customer_name_input, pattern="^rental_back_name$"),
                    CallbackQueryHandler(show_rental_hub, pattern="^rental_hub$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, rental_handle_phone_input),
                ],
                States.RENTAL_ENTER_CUSTOMER_TAX_ID: [
                    CallbackQueryHandler(rental_handle_tax_input, pattern="^rental_tax_skip$"),
                    CallbackQueryHandler(_render_customer_phone_input, pattern="^rental_back_phone$"),
                    CallbackQueryHandler(show_rental_hub, pattern="^rental_hub$"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, rental_handle_tax_input),
                ],
                States.RENTAL_FINAL_CONFIRM: [
                    CallbackQueryHandler(rental_finalize_order, pattern="^rental_confirm_create$"),
                    CallbackQueryHandler(_render_customer_type_selection, pattern="^rental_back_cust_type$"),
                    CallbackQueryHandler(show_rental_hub, pattern="^rental_hub$"),
                ],
            },
            fallbacks=[
                CallbackQueryHandler(show_rental_hub, pattern="^rental_hub$"),
                CallbackQueryHandler(main_menu, pattern="^main_menu$"),
            ],
            allow_reentry=True,
        )

        # --- ДІАЛОГ ЗАВАНТАЖЕННЯ ПІДПИСАНОГО ДОГОВОРУ (.P7S / СКАН) ТА КВИТАНЦІЇ IBAN ---
        rental_upload_conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(rental_start_upload_document, pattern="^rental_upload_(signed|payment):\\d+$"),
            ],
            states={
                States.RENTAL_UPLOAD_SIGNED_DOC: [
                    MessageHandler(
                        (filters.Document.ALL | filters.PHOTO) & ~filters.COMMAND,
                        rental_receive_uploaded_document,
                    ),
                    CallbackQueryHandler(show_rental_contract_detail, pattern="^rental_contract_view:\\d+$"),
                ],
            },
            fallbacks=[
                CallbackQueryHandler(show_my_rental_contracts, pattern="^rental_my_contracts$"),
                CallbackQueryHandler(show_rental_hub, pattern="^rental_hub$"),
                CallbackQueryHandler(main_menu, pattern="^main_menu$"),
            ],
            allow_reentry=True,
        )

        # Додавання всіх conversation handlers
        self.app.add_handler(complaint_conv)
        self.app.add_handler(thanks_conv)
        self.app.add_handler(suggestion_conv)
        self.app.add_handler(museum_conv)
        self.app.add_handler(accessible_conv)
        self.app.add_handler(rental_conv)
        self.app.add_handler(rental_upload_conv)

        logger.info("✅ All handlers configured")

        # --- ГОЛОВНЕ МЕНЮ ---
        self.app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))

        # --- РОЗДІЛ ОРЕНДИ (КЛІЄНТСЬКИЙ ХАБ ТА ШТАБ КП ОМЕТ) ---
        self.app.add_handler(CallbackQueryHandler(show_rental_hub, pattern="^rental_hub$"))
        self.app.add_handler(CallbackQueryHandler(show_rental_rules_info, pattern="^rental_rules_info$"))
        self.app.add_handler(CallbackQueryHandler(show_my_rental_contracts, pattern="^rental_my_contracts$"))
        self.app.add_handler(CallbackQueryHandler(show_rental_contract_detail, pattern="^rental_contract_view:\\d+$"))
        self.app.add_handler(CallbackQueryHandler(handle_rental_redownload_pdfs, pattern="^rental_redownload:\\d+$"))
        self.app.add_handler(CallbackQueryHandler(rental_handle_resend_docs, pattern="^rental_resend_docs:\\d+$"))
        self.app.add_handler(CallbackQueryHandler(rental_handle_delete_file, pattern="^rental_del_file$"))
        self.app.add_handler(CallbackQueryHandler(handle_client_pick_order_slot, pattern="^rental_pick_order_slot:\\d+:.+$"))
        self.app.add_handler(CallbackQueryHandler(handle_rental_staff_callback, pattern="^rental_staff:"))
        self.app.add_handler(CallbackQueryHandler(handle_depot_slots_callback, pattern="^depot_slots:"))
        self.app.add_handler(CallbackQueryHandler(handle_analytics_callback, pattern="^rental_analytics:"))

        # --- ОБРОБНИКИ МЕНЮ 1-ГО РІВНЯ ---
        self.app.add_handler(CallbackQueryHandler(realtime_transport, pattern="^realtime_transport$"))
        self.app.add_handler(CallbackQueryHandler(news_client_list, pattern="^news_client_list(:.*)?$"))
        self.app.add_handler(CallbackQueryHandler(news_client_view, pattern="^news_client_view(:.*)?$"))
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
        self.app.add_handler(CallbackQueryHandler(admin_show_bookings, pattern="^admin_show_bookings(:\\d+)?$"))
        self.app.add_handler(CallbackQueryHandler(admin_show_holiday_bookings, pattern="^admin_show_holiday_bookings(:\\d+)?$"))
        self.app.add_handler(CallbackQueryHandler(admin_export_doc_select, pattern="^admin_export_doc_select:(regular|holiday)$"))
        self.app.add_handler(CallbackQueryHandler(admin_export_doc_generate, pattern="^admin_export_doc_gen:(regular|holiday):.+$"))
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
        self.app.add_handler(CallbackQueryHandler(vacancy_show_phone, pattern="^vacancy_show_phone:"))


        # Обробник "Загублені речі" (БД-керований, з пагінацією — див. handlers/lost_items_handlers.py)
        self.app.add_handler(CallbackQueryHandler(show_lost_items_menu, pattern="^lost_items$"))
        self.app.add_handler(CallbackQueryHandler(show_lost_items_category, pattern="^lost_items_cat:"))

        # === 👇 ГЛОБАЛЬНИЙ ПЕРЕХОПЛЮВАЧ (Штабний ввід / Anti-Spam / Cleaner) 👇 ===
        # Спочатку перевіряємо, чи це відповідь співробітника штабу оренди (слоти, борт/водій або 'Коментар: ...').
        # Якщо ні — передаємо стандартному чистильнику для приватних чатів.
        async def _staff_or_unexpected_router(update, context):
            if await handle_staff_group_text_input(update, context):
                return
            await handle_unexpected_message(update, context)

        self.app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, _staff_or_unexpected_router))



    async def start(self):
        logger.info("🚀 Starting bot polling...")
        await self.app.run_polling()

    #async def stop(self):
       # """Зупинка бота"""
        # ... (код без змін) ...