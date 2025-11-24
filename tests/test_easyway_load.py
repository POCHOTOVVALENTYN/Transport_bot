# tests/test_easyway_load.py
import asyncio
import aiohttp
import time
from services.easyway_service import easyway_service


async def test_easyway_concurrent_requests():
    """Тест: 100 одночасних запитів до EasyWay"""
    tasks = []
    results = {"success": 0, "timeout": 0, "error": 0}

    start_time = time.time()

    for i in range(100):
        search_terms = ["Привоз", "Вокзал", "Шевченка"]
        term = search_terms[i % len(search_terms)]

        task = easyway_service.get_places_by_name(term)
        tasks.append(task)

    responses = await asyncio.gather(*tasks, return_exceptions=True)

    for resp in responses:
        if isinstance(resp, Exception):
            if "timeout" in str(resp).lower():
                results["timeout"] += 1
            else:
                results["error"] += 1
        elif not resp.get("error"):
            results["success"] += 1
        else:
            results["error"] += 1

    elapsed = time.time() - start_time

    print(f"""
    ✅ EasyWay Load Test Results:
    - Total requests: 100
    - Success: {results['success']}
    - Timeouts: {results['timeout']}
    - Errors: {results['error']}
    - Duration: {elapsed:.2f}s
    - Avg response time: {elapsed / 100 * 1000:.0f}ms
    """)

# Запуск: asyncio.run(test_easyway_concurrent_requests())