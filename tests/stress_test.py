# tests/stress_test.py
from locust import HttpUser, task, between
import random
import json
from datetime import datetime


class TransportBotUser(HttpUser):
    wait_time = between(1, 5)  # Затримка між запитами

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_id = random.randint(100000, 199999)
        self.chat_id = self.user_id

    @task(10)  # Вес 10: часто виконується
    def search_accessible_transport(self):
        """Симуляція пошуку інклюзивного транспорту"""
        search_term = random.choice([
            "Привоз", "Залізничний вокзал", "Аркадія",
            "Шевченка", "Вокзал", "Театр"
        ])
        # Імітуємо запит до Telegram (webhook або polling)
        self.client.post(
            "/accessible_search",
            json={
                "user_id": self.user_id,
                "search_term": search_term
            }
        )

    @task(5)  # Вес 5: середня частота
    def view_tickets(self):
        """Перегляд квитків"""
        self.client.get(
            f"/tickets?user_id={self.user_id}"
        )

    @task(3)  # Вес 3: менш часто
    def submit_complaint(self):
        """Подання скарги"""
        complaint = {
            "user_id": self.user_id,
            "problem": "Водій був неввічливий",
            "route": "7",
            "board_number": "4015"
        }
        self.client.post("/complaint", json=complaint)

    @task(2)  # Вес 2: рідко
    def museum_booking(self):
        """Бронювання музею"""
        booking = {
            "user_id": self.user_id,
            "date": "25.12.2025 14:00",
            "people_count": random.randint(1, 5),
            "name": f"User {self.user_id}",
            "phone": "0991234567"
        }
        self.client.post("/museum_booking", json=booking)