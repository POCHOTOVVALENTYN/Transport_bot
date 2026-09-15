# Callback data
class CallbackData:
    MAIN_MENU = "main_menu"
    FEEDBACK = "feedback"
    COMPLAINT = "complaint"
    SUGGESTION = "suggestion"
    THANKS = "thanks"

# Sheet names
SHEET_NAMES = {
    "complaints": "Скарги",
    "suggestions": "Пропозиції",
    "thanks": "Подяки"
}

# Ticket status
class TicketStatus:
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"

# Emoji
EMOJI = {
    "back": "⬅️",
    "ok": "✅",
    "error": "❌",
    "new": "🆕",
    "in_progress": "⚙️",
    "resolved": "✅",
    "closed": "🔒"
}


# Ліміти запису на екскурсії до Музею КП "ОМЕТ"
class MuseumLimits:
    HOLIDAY_MAX_TOTAL = 40        # Максимум людей на святкову екскурсію (сумарно на дату)
    HOLIDAY_MAX_PER_BOOKING = 2   # Максимум людей в одній заявці на святкову екскурсію
    REGULAR_MAX_TOTAL = 60        # Максимум людей на звичайну екскурсію (сумарно на дату)
    REGULAR_MAX_PER_BOOKING = 5   # Максимум людей в одній заявці на звичайну екскурсію
