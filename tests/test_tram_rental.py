"""Unit tests for Tram Rental Service and route calculation engine."""
import os
import pytest
from services.tram_rental_service import (
    RentalCalculationInput,
    calculate_tram_rental_trip,
    find_shortest_tram_path,
    generate_rental_route_sheet_pdf,
    get_available_turning_loops,
)


def test_shortest_path_vrm_to_starosinna():
    """Verify exact path from VRM to Starosinna includes Мечникова and matches distance."""
    result = find_shortest_tram_path("ВРМ", "Старосінна площа")
    assert result["distance_km"] == 2.70
    assert result["duration_minutes"] == 14
    assert "вул. Мечникова" in result["path"]
    assert result["path"][0] == "ВРМ"
    assert result["path"][-1] == "пл. Старосінна"


def test_circular_rental_calculation():
    """Verify circular rental trip enforces intermediate loop and correctly aggregates 3 phases."""
    calc_input = RentalCalculationInput(
        wagon_type="retro",
        depot_base="ВРМ",
        pickup_stop="Старосінна площа",
        dropoff_stop="Старосінна площа",
        intermediate_loop="Аркадія",
        loop_wait_minutes=10
    )
    res = calculate_tram_rental_trip(calc_input)
    assert res.is_success is True
    assert res.phase_1_dispatch.distance_km == 2.70
    assert res.phase_1_dispatch.motion_minutes == 14
    assert res.phase_2_rental.distance_km == 14.40
    assert res.phase_2_rental.motion_minutes == 58
    assert res.phase_2_rental.wait_minutes == 10
    assert "вул. Преображенська" in res.phase_2_rental.stops_path
    assert "вул. Європейська" in res.phase_2_rental.stops_path
    assert res.phase_3_return.distance_km == 2.70
    assert res.phase_3_return.motion_minutes == 14
    assert res.total_billable_km == 19.80
    assert res.total_duration_minutes == 96


def test_circular_rental_missing_loop_raises_error():
    """Verify circular route without loop raises ValueError."""
    calc_input = RentalCalculationInput(
        wagon_type="retro",
        pickup_stop="Старосінна площа",
        dropoff_stop="Старосінна площа",
        intermediate_loop=None
    )
    with pytest.raises(ValueError) as exc_info:
        calculate_tram_rental_trip(calc_input)
    assert "проміжне розворотне кільце" in str(exc_info.value)


def test_route_sheet_pdf_generation(tmp_path):
    """Verify route sheet PDF is generated and has non-zero size."""
    calc_input = RentalCalculationInput(
        wagon_type="retro",
        pickup_stop="Старосінна площа",
        dropoff_stop="Старосінна площа",
        intermediate_loop="Аркадія",
        loop_wait_minutes=5
    )
    res = calculate_tram_rental_trip(calc_input)
    pdf_path = str(tmp_path / "test_sheet.pdf")
    generated_path = generate_rental_route_sheet_pdf(res, output_pdf_path=pdf_path)
    assert os.path.exists(generated_path)
    assert os.path.getsize(generated_path) > 1000


def test_available_turning_loops_count():
    """Verify all 22+ official turning loops are present."""
    loops = get_available_turning_loops()
    assert len(loops) >= 22
    assert "Аркадія" in loops
    assert "Куликове поле" in loops
    assert "Старосінна площа" in loops
