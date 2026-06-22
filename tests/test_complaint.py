import pytest
from handlers.complaint_handlers import clean_phone, is_valid_email
from services.tickets_service import TicketsService
from database.db import AsyncSessionLocal, Feedback
from sqlalchemy import select

def test_clean_phone():
    assert clean_phone("0951234567") == "+380951234567"
    assert clean_phone("+380951234567") == "+380951234567"
    assert clean_phone("380951234567") == "+380951234567"
    assert clean_phone("invalid-phone") is None
    assert clean_phone("123") is None

def test_is_valid_email():
    assert is_valid_email("user@example.com") is True
    assert is_valid_email("user.name+label@example.co.uk") is True
    assert is_valid_email("invalid-email") is False
    assert is_valid_email("user@com") is False

@pytest.mark.asyncio
async def test_create_complaint_ticket_db():
    service = TicketsService()
    complaint_data = {
        "problem": "Тестова скарга на водія",
        "route": "10",
        "board_number": "3028",
        "user_name": "Іван Іванов",
        "user_phone": "+380951234567",
        "user_email": "ivan@example.com"
    }
    
    result = await service.create_complaint_ticket(telegram_id=99999, complaint_data=complaint_data)
    assert result["success"] is True
    assert "ID:" in result["message"]
    
    # Verify it exists in DB
    async with AsyncSessionLocal() as session:
        q = select(Feedback).where(Feedback.user_id == 99999, Feedback.category == "complaint")
        res = await session.execute(q)
        feedback = res.scalars().first()
        assert feedback is not None
        assert feedback.text == "Тестова скарга на водія"
        assert feedback.route == "10"
        assert feedback.board_number == "3028"
        assert feedback.user_name == "Іван Іванов"
        assert feedback.user_phone == "+380951234567"
        assert feedback.user_email == "ivan@example.com"
        
        # Cleanup
        await session.delete(feedback)
        await session.commit()
