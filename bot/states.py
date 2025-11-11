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

    # Нові стани для Пошуку Інклюзивного Транспорту
    ACCESSIBLE_CHOOSE_TYPE = 30  # Крок 1: Трамвай / Тролейбус
    ACCESSIBLE_CHOOSE_ROUTE = 31  # Крок 2: Маршрут 5, 7, 10...
    ACCESSIBLE_CHOOSE_DIRECTION = 32  # Крок 3: Напрямок
    ACCESSIBLE_CHOOSE_STOP_METHOD = 33  # Крок 4: Гео / Список
    ACCESSIBLE_GET_LOCATION = 34  # Крок 4А: Очікування гео
    ACCESSIBLE_CHOOSE_FROM_LIST = 35  # Крок 4Б: Очікування вибору зі списку
    ACCESSIBLE_AWAIT_NOTIFY = 36  # Крок 5: Очікування "Повідомити"