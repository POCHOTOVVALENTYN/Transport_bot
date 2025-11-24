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
        # Крок 1: Запит дат
        payload_dates = generate_telegram_update(self.update_id, self.user_id, "Музей")
        self.client.post("/webhook", json=payload_dates)
        self.update_id += 1

        # Крок 2: Вибір дати (імітація CallbackQuery або тексту)
        # Тут треба адаптувати під вашу структуру хендлерів
        payload_book = generate_telegram_update(self.update_id, self.user_id, "Забронювати на 12:00")
        self.client.post("/webhook", json=payload_book)
        self.update_id += 1

    @task(1)
    def feedback(self):
        """Сценарій: Відгук (Google Sheets)"""
        payload = generate_telegram_update(self.update_id, self.user_id, "Скарги та пропозиції")
        self.client.post("/webhook", json=payload)
        self.update_id += 1