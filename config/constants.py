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