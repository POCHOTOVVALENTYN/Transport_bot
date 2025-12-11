"""

Стани для ConversationHandlers (python-telegram-bot).
Це прості INTEGER константи, які відслідковують етап діалогу.
"""


class States:
    """Стани для ConversationHandlers"""

    # ========== СКАРГИ ==========
    COMPLAINT_AWAIT_TEXT = 1
    COMPLAINT_CONFIRMATION = "COMPLAINT_CONFIRMATION"

    # ========== ПОДЯКИ (V2 - Апгрейд) ==========
    # Крок 0: Вибір типу подяки
    THANKS_CHOOSE_TYPE = 2

    # ГІЛКА 1: КОНКРЕТНА ПОДЯКА
    THANKS_SPECIFIC_CHOOSE_TRANSPORT = 3  # Вибір: Трамвай чи Тролейбус?
    THANKS_SPECIFIC_BOARD_NUMBER = 4  # Введення бортового номера
    THANKS_SPECIFIC_REASON = 5  # За що вдячні? + ПІБ водія
    THANKS_SPECIFIC_EMAIL = 6  # Email

    # ГІЛКА 2: ЗАГАЛЬНА ПОДЯКА
    THANKS_GENERAL_MESSAGE = 7  # Суть вдячності
    THANKS_GENERAL_NAME = 8  # П.І.Б. користувача
    THANKS_GENERAL_EMAIL = 9  # Email
    THANKS_CONFIRMATION = "THANKS_CONFIRMATION"

    # ========== МУЗЕЙ ==========
    MUSEUM_DATE = 11
    MUSEUM_PEOPLE_COUNT = 12
    MUSEUM_NAME = 13
    MUSEUM_PHONE = 14

    # ========== АДМІН-ПАНЕЛЬ ==========
    ADMIN_STATE_ADD_DATE = 16
    ADMIN_STATE_DEL_DATE_CONFIRM = 17
    ADMIN_BROADCAST_TEXT = 50
    ADMIN_BROADCAST_CONFIRM = 51

    # ========== ПРОПОЗИЦІЇ ==========
    SUGGESTION_TEXT = 20
    SUGGESTION_GET_NAME = 22
    SUGGESTION_GET_PHONE = 23
    COMPLAINT_EMAIL = 24
    SUGGESTION_EMAIL = 25
    SUGGESTION_CONFIRMATION = "SUGGESTION_CONFIRMATION"

    # ========== ІНКЛЮЗИВНИЙ ТРАНСПОРТ ==========
    ACCESSIBLE_SEARCH_STOP = 30
    ACCESSIBLE_SELECT_STOP = 31
    ACCESSIBLE_SHOWING_RESULTS = 32