# tests/test_db_load.py
import asyncio
import time
from database.db import AsyncSessionLocal, Feedback


async def test_db_concurrent_inserts():
    """Тест: 500 одночасних INSERT в БД"""
    tasks = []
    start_time = time.time()

    for i in range(500):
        async def insert_feedback(index):
            try:
                async with AsyncSessionLocal() as session:
                    feedback = Feedback(
                        ticket_id=f"TEST-{index:05d}",
                        category="suggestion",
                        text=f"Тестова пропозиція {index}",
                        user_id=100000 + index,
                        status="new"
                    )
                    session.add(feedback)
                    await session.commit()
                    return True
            except Exception as e:
                return False

        tasks.append(insert_feedback(i))

    results = await asyncio.gather(*tasks)

    elapsed = time.time() - start_time

    successes = sum(1 for r in results if r is True)
    failures = 500 - successes

    print(f"""
    ✅ SQLite Load Test Results:
    - Total inserts: 500
    - Success: {successes}
    - Failures: {failures}
    - Duration: {elapsed:.2f}s
    - Avg insert time: {elapsed / 500 * 1000:.0f}ms
    - Inserts per second: {500 / elapsed:.1f}
    """)

# Запуск: asyncio.run(test_db_concurrent_inserts())