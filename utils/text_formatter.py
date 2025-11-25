def format_ticket_id() -> str:
    """Генерація ID тікету"""
    from datetime import datetime
    import uuid
    return f"CMP-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

def get_status_emoji(status: str) -> str:
    """Отримання emoji за статусом"""
    status_map = {
        'new': '🆕 Нова',
        'acknowledged': '👀 Прийнята',
        'in_progress': '⚙️ В роботі',
        'resolved': '✅ Вирішена',
        'closed': '🔒 Закрита'
    }
    return status_map.get(status, status)

def get_priority_emoji(priority: str) -> str:
    """Отримання emoji за пріоритетом"""
    priority_map = {
        'low': '🟢 Низька',
        'medium': '🟡 Середня',
        'high': '🔴 Висока',
        'critical': '🚨 Критична'
    }
    return priority_map.get(priority, priority)

def format_feedback_message(data: dict) -> str:
    """
    Форматує дані відгуку/подяки в один рядок для логування або відображення.
    """
    category = data.get('category', 'Звернення')
    text = data.get('text', 'Без тексту')
    route = data.get('route', 'Не вказано')
    board = data.get('board', 'Не вказано')
    name = data.get('name', 'Анонім')
    phone = data.get('phone', '')

    return (
        f"📝 [{category}]\n"
        f"👤 Від: {name} ({phone})\n"
        f"🚌 Маршрут: {route} | Борт: {board}\n"
        f"💬 Текст: {text}"
    )