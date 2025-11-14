# config/easyway_config.py

from dataclasses import dataclass


@dataclass
class EasyWayConfig:
    """Конфігурація API EasyWay"""

    BASE_URL = "https://api.easyway.info"
    LOGIN = "odesainclusive"
    PASSWORD = "ndHdy2Ytw2Ois"

    # ⭐ НОВИЙ ПАРАМЕТР
    STOP_INFO_VERSION = "1.2"  # Замість "1.0"

    # ⭐ HARDCODED МІСТО
    DEFAULT_CITY = "odesa"

    DEFAULT_FORMAT = "json"

    # Зберігаємо перелік типів для фільтрації
    TRANSPORT_TYPES = {
        "bus": "🚌 Автобус",
        "trol": "🚎 Тролейбус",
        "tram": "🚊 Трамвай",
        "marshrutka": "🚐 Маршрутка",
    }

    # Іконки для джерел часу
    TIME_SOURCE_ICONS = {
        "gps": "📍",
        "schedule": "📋",
        "interval": "⏱️",
    }