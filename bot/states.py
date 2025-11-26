from aiogram.dispatcher.filters.state import State, StatesGroup

class GratitudeForm(StatesGroup):
    waiting_for_type_selection = State()      # Вибір: Конкретна чи Загальна
    # Гілка КОНКРЕТНОЇ подяки
    waiting_for_transport_type = State()      # Вибір: Трамвай чи Тролейбус
    waiting_for_vehicle_number = State()      # Введення бортового номера
    waiting_for_specific_details = State()    # Текст подяки + ПІБ водія
    # Гілка ЗАГАЛЬНОЇ подяки
    waiting_for_general_details = State()     # Суть подяки
    waiting_for_user_name = State()           # ПІБ користувача
    # Фінал (спільний)
    waiting_for_email = State()               # Email


class States:
    """Стани для ConversationHandlers"""

    # Стани для скарг
    COMPLAINT_AWAIT_TEXT = 1

    # --- ОНОВЛЕНІ СТАНИ ДЛЯ ПОДЯК ---
    # Ми використовуємо ці назви у handlers/thanks_handlers.py
    THANKS_TEXT = 6  # Було THANKS_PROBLEM
    THANKS_ROUTE = 7
    THANKS_BOARD = 8
    THANKS_NAME = 19  # Новий стан для імені (замість старих 18/19/20)

    # Нові стани для пропозицій
    SUGGESTION_TEXT = 9

    # Реєстрація в музей
    MUSEUM_DATE = 11
    MUSEUM_PEOPLE_COUNT = 12
    MUSEUM_NAME = 13
    MUSEUM_PHONE = 14

    # Адмін-панель Музею
    ADMIN_STATE_ADD_DATE = 16
    ADMIN_STATE_DEL_DATE_CONFIRM = 17
    ADMIN_BROADCAST_TEXT = 50
    ADMIN_BROADCAST_CONFIRM = 51

    # Старі стани подяк (THANKS_ASK_SPECIFIC і т.д.) можна видалити або залишити,
    # але ми їх більше не використовуємо в коді.

    # Пропозиції (продовження)
    SUGGESTION_GET_NAME = 22
    SUGGESTION_GET_PHONE = 23
    COMPLAINT_EMAIL = 24
    SUGGESTION_EMAIL = 25

    # Пошук Інклюзивного Транспорту
    ACCESSIBLE_SEARCH_STOP = 30
    ACCESSIBLE_SELECT_STOP = 31
    ACCESSIBLE_SHOWING_RESULTS = 32