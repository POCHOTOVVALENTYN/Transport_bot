# bot/states.py

class States:
    """Стани для ConversationHandlers"""

    # Стани для скарг (оновлені, 1, 2, 3, 4, 5 + 15)
    COMPLAINT_AWAIT_TEXT = 1

    # Стани для подяк (існуючі)
    THANKS_PROBLEM = 6
    THANKS_ASK_SPECIFIC = 18  # <-- НОВИЙ: Запитати "Так/Ні"
    THANKS_ROUTE = 7
    THANKS_BOARD = 8
    THANKS_ASK_NAME = 19  # <-- НОВИЙ: Запитати "Так/Ні" (анонім)
    THANKS_GET_NAME = 20  # <-- НОВИЙ: Отримати ПІБ

    # Нові стани для пропозицій
    SUGGESTION_TEXT = 9
    SUGGESTION_GET_NAME = 22  # <-- НОВИЙ: Отримати ПІБ
    SUGGESTION_GET_PHONE = 23
    COMPLAINT_EMAIL = 24
    SUGGESTION_EMAIL = 25

    # Нові стани для реєстрації в музей
    MUSEUM_DATE = 11
    MUSEUM_PEOPLE_COUNT = 12
    MUSEUM_NAME = 13  # <--- ЗМІНЕНО
    MUSEUM_PHONE = 14

    # Нові стани для Адмін-панелі Музею
    ADMIN_STATE_ADD_DATE = 16
    ADMIN_STATE_DEL_DATE_CONFIRM = 18