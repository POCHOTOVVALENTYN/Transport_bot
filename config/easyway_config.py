# config/easyway_config.py

from dataclasses import dataclass


@dataclass
class EasyWayConfig:
    """Конфігурація API EasyWay v1.2"""

    BASE_URL = "https://api.easyway.info"
    LOGIN = "odesainclusive"
    PASSWORD = "ndHdy2Ytw2Ois"

    # ⭐ ВЕРСІЯ API (з GPS-даними)
    STOP_INFO_VERSION = "1.2"

    # Місто
    DEFAULT_CITY = "odesa"

    # Формат відповіді
    DEFAULT_FORMAT = "json"

    # Типи транспорту
    TRANSPORT_TYPES = {
        "bus": "🚌 Автобус",
        "trol": "🚎 Тролейбус",
        "tram": "🚊 Трамвай",
        "marshrutka": "🚐 Маршрутка",
    }

    # Іконки для джерел часу
    TIME_SOURCE_ICONS = {
        "gps": "🛰️",
        "schedule": "🗓️",
        "interval": "⏳",
        "unknown": "❓"
    }