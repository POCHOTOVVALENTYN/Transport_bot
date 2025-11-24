# tests/webhook_for_test.py (Тестовий webhook)
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import logging

app = FastAPI()
logger = logging.getLogger("test_webhook")

@app.post("/accessible_search")
async def handle_accessible_search(data: dict):
    """Симуляція обробки пошуку"""
    logger.info(f"Search: {data['search_term']} from {data['user_id']}")
    # Тут виконуємо реальну логіку з вашого бота
    return {"status": "ok", "results": 5}

@app.post("/complaint")
async def handle_complaint(data: dict):
    logger.info(f"Complaint from {data['user_id']}")
    return {"ticket_id": "CMP-20250121-ABC123"}

@app.post("/museum_booking")
async def handle_museum_booking(data: dict):
    logger.info(f"Museum booking from {data['user_id']}")
    return {"booking_id": "BOOK-001", "status": "confirmed"}

# Запуск: uvicorn tests/webhook_for_test.py --port 8001