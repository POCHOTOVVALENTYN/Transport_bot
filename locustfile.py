import json
import random
from locust import HttpUser, task, between


# Приклад JSON-апдейту від Telegram
def generate_telegram_update(update_id, user_id, text):
    return {
        "update_id": update_id,
        "message": {
            "message_id": random.randint(1000, 9999),
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": f"User{user_id}",
                "username": f"user_{user_id}",
                "language_code": "uk"
            },
            "chat": {
                "id": user_id,
                "first_name": f"User{user_id}",
                "type": "private"
            },
            "date": 1686000000,
            "text": text
        }
    }


def generate_callback_update(update_id, user_id, callback_data, message_id=None):
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb_{update_id}_{user_id}",
            "from": {
                "id": user_id,
                "is_bot": False,
                "first_name": f"User{user_id}",
                "username": f"user_{user_id}",
                "language_code": "uk"
            },
            "message": {
                "message_id": message_id or random.randint(1000, 9999),
                "chat": {
                    "id": user_id,
                    "first_name": f"User{user_id}",
                    "type": "private"
                },
                "date": 1686000000,
                "text": "Меню"
            },
            "data": callback_data
        }
    }


class TransportBotUser(HttpUser):
    # 👇 ДОДАЙТЕ ЦЕЙ РЯДОК ОБОВ'ЯЗКОВО 👇
    host = "http://localhost:8001"

    wait_time = between(1, 5)  # Пауза між діями користувача (1-5 сек)

    def on_start(self):
        self.user_id = random.randint(1000000, 9999999)
        self.update_id = 1

    @task(3)
    def check_transport(self):
        """Сценарій: Перевірка транспорту (EasyWay)"""
        payload = generate_telegram_update(self.update_id, self.user_id, "Трамвай 10")
        # Надсилаємо POST на ендпоінт вашого бота
        self.client.post("/webhook", json=payload)
        self.update_id += 1

    @task(1)
    def book_museum(self):
        """Сценарій: Бронювання музею (DB Write + Google Sheets)"""
        # Крок 1: Відкриття меню музею
        payload_menu = generate_callback_update(self.update_id, self.user_id, "museum_menu")
        self.client.post("/webhook", json=payload_menu)
        self.update_id += 1

        # Крок 2: Старт реєстрації
        payload_start = generate_callback_update(self.update_id, self.user_id, "museum:register_start")
        self.client.post("/webhook", json=payload_start)
        self.update_id += 1

    @task(1)
    def feedback(self):
        """Сценарій: Відгук (Google Sheets)"""
        payload_menu = generate_callback_update(self.update_id, self.user_id, "feedback_menu")
        self.client.post("/webhook", json=payload_menu)
        self.update_id += 1

        payload = generate_telegram_update(self.update_id, self.user_id, "Тестове звернення для перевірки")
        self.client.post("/webhook", json=payload)
        self.update_id += 1