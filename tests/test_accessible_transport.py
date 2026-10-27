import pytest
from services.easyway_service import easyway_service, safe_int, safe_float


def test_safe_int():
    assert safe_int(None) == 0
    assert safe_int("") == 0
    assert safe_int(123) == 123
    assert safe_int("123") == 123
    assert safe_int("123.7") == 123
    assert safe_int("invalid", default=5) == 5
    assert safe_int(None, default=99) == 99


def test_safe_float():
    assert safe_float(None) == 0.0
    assert safe_float("") == 0.0
    assert safe_float(4.5) == 4.5
    assert safe_float("4.5") == 4.5
    assert safe_float("12") == 12.0
    assert safe_float("invalid", default=9999.0) == 9999.0
    assert safe_float(None, default=9999.0) == 9999.0


def test_parse_stop_info_v12_with_null_fields():
    raw_data = {
        "id": "364",
        "title": 'Ринок "Привоз"',
        "lat": None,
        "lng": None,
        "routes": [
            {
                "id": "8",
                "title": "10",
                "direction": None,
                "directionTitle": "пл. Тираспольська",
                "transportName": "Трамвай",
                "transportKey": "tram",
                "handicapped": False,
                "bortNumber": "4018",
                "timeLeft": None,
                "timeLeftFormatted": "4хв",
                "timeSource": "gps"
            },
            {
                "id": "210",
                "title": "7",
                "direction": "",
                "directionTitle": "Таврія В",
                "transportName": "Трамвай",
                "transportKey": "tram",
                "handicapped": True,
                "bortNumber": "4046",
                "timeLeft": "",
                "timeLeftFormatted": "",
                "timeSource": "unknown"
            }
        ]
    }

    parsed = easyway_service._parse_stop_info_v12(raw_data)
    assert "error" not in parsed
    assert parsed["id"] == 364
    assert parsed["lat"] == 0.0
    assert parsed["lng"] == 0.0
    assert len(parsed["routes"]) == 2

    route1 = parsed["routes"][0]
    assert route1["direction"] == 0
    assert route1["time_left"] == 9999.0
    assert route1["handicapped"] is False

    route2 = parsed["routes"][1]
    assert route2["direction"] == 0
    assert route2["time_left"] == 9999.0
    assert route2["handicapped"] is True


def test_parse_stop_info_v12_with_api_error():
    raw_data = {"error": "Stop not found"}
    parsed = easyway_service._parse_stop_info_v12(raw_data)
    assert parsed.get("error") == "Stop not found"


def test_parse_stop_info_v12_with_nested_transports():
    raw_data = {
        "id": 100,
        "title": "Тестова зупинка",
        "lat": "46.48",
        "lng": "30.73",
        "transports": [
            {
                "routes": [
                    {
                        "id": 5,
                        "title": "28",
                        "transportKey": "tram",
                        "handicapped": True,
                        "timeLeft": "5.5"
                    }
                ]
            }
        ]
    }

    parsed = easyway_service._parse_stop_info_v12(raw_data)
    assert "error" not in parsed
    assert len(parsed["routes"]) == 1
    assert parsed["routes"][0]["title"] == "28"
    assert parsed["routes"][0]["time_left"] == 5.5
    assert parsed["routes"][0]["handicapped"] is True


def test_parse_places_response():
    raw_data = {
        "item": [
            {
                "@attributes": {"type": "stop"},
                "id": "364",
                "title": 'Ринок "Привоз"',
                "routes": {
                    "route": [
                        {"@attributes": {"type": "tram"}, "title": "7"},
                        {"@attributes": {"type": "trol"}, "title": "10"}
                    ]
                }
            },
            {
                "@attributes": {"type": "place"},
                "title": "Автостанція"
            }
        ]
    }

    parsed = easyway_service._parse_places_response(raw_data)
    assert "error" not in parsed
    assert len(parsed["stops"]) == 1
    stop = parsed["stops"][0]
    assert stop["id"] == 364
    assert "🚋 7" in stop["routes_summary"]
    assert "🚎 10" in stop["routes_summary"]


def test_parse_route_gps_handicapped_filtering():
    raw_data = {
        "vehicle": [
            {
                "id": "7152",
                "handicapped": 0,
                "data_relevance": 1,
                "lat": "46.46",
                "lng": "30.73",
                "direction": "1"
            },
            {
                "id": "4046",
                "handicapped": 1,
                "data_relevance": 1,
                "lat": "46.47",
                "lng": "30.74",
                "direction": "0"
            },
            {
                "id": "4050",
                "handicapped": "1",
                "data_relevance": 1,
                "lat": None,
                "lng": None,
                "direction": None
            }
        ]
    }

    vehicles = easyway_service._parse_route_gps(raw_data)
    assert len(vehicles) == 2
    assert vehicles[0]["raw_id"] == "4046"
    assert vehicles[0]["direction"] == 0
    assert vehicles[1]["raw_id"] == "4050"
    assert vehicles[1]["lat"] == 0.0
    assert vehicles[1]["direction"] == 0
