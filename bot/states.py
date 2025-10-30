# bot/states.py

class States:
    """Стани для ConversationHandlers"""

    # Стани для скарг (існуючі)
    COMPLAINT_PROBLEM = 1
    COMPLAINT_ROUTE = 2
    COMPLAINT_BOARD = 3
    COMPLAINT_DATETIME = 4
    COMPLAINT_CONTACT = 5

    # Стани для подяк (існуючі)
    THANKS_PROBLEM = 6
    THANKS_ROUTE = 7
    THANKS_BOARD = 8

    # Нові стани для пропозицій
    SUGGESTION_TEXT = 9
    SUGGESTION_CONTACT = 10

    # Нові стани для реєстрації в музей
    MUSEUM_DATE = 11
    MUSEUM_PEOPLE_COUNT = 12
    MUSEUM_CONTACT_INFO = 13