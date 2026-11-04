"""Comprehensive matrix and stress tests for Odesa tram rental routing.

Verifies complete connectivity across all 26 official turning loops,
validates 3-phase rental cycles (dispatch, motion, return), checks speeds,
and ensures absence of disconnected nodes or phantom shortcuts.
"""
import pytest
from services.tram_rental_service import (
    OFFICIAL_TURNING_LOOPS,
    TRAM_TRACK_GRAPH,
    RentalCalculationInput,
    calculate_tram_rental_trip,
    find_shortest_tram_path,
    normalize_stop_name,
)


def test_all_official_loops_in_track_graph() -> None:
    """Verifies that all unique turning loops exist as physical nodes in the track graph."""
    unique_loops = set(normalize_stop_name(loop_name) for loop_name in OFFICIAL_TURNING_LOOPS)
    missing_loops = [loop for loop in unique_loops if loop not in TRAM_TRACK_GRAPH]
    assert not missing_loops, f"Turning loops missing from track graph: {missing_loops}"


def test_complete_network_reachability() -> None:
    """Tests reachability between all pairs of unique turning loops."""
    unique_loops = sorted(list(set(normalize_stop_name(l) for l in OFFICIAL_TURNING_LOOPS)))
    unreachable_pairs = []

    for start_node in unique_loops:
        for target_node in unique_loops:
            if start_node == target_node:
                continue
            path_result = find_shortest_tram_path(start_node, target_node)
            if not path_result or not path_result.get("path"):
                unreachable_pairs.append((start_node, target_node))

    assert not unreachable_pairs, f"Found unreachable loop pairs: {unreachable_pairs[:5]}"


def test_cross_city_rental_routes() -> None:
    """Verifies end-to-end 3-phase rental calculations across major city sectors."""
    test_cases = [
        ("пл. Старосінна", "Аркадія", "ВРМ"),
        ("пл. Тираспольська", "станція Застава ІІ", "ВРМ"),
        ("Куликове поле", "16-а станція Великого Фонтану", "ТД-1"),
        ("пл. Старосінна", "селище Люстдорф", "ТД-1"),
        ("Пересипський міст", "Лузанівка", "ТД-2"),
        ("Херсонський сквер", "Хаджибейський лиман", "ТД-2"),
        ("пл. Старосінна", "Парк ім. Тараса Шевченка", "ВРМ"),
    ]

    for pickup, dropoff, depot in test_cases:
        request_input = RentalCalculationInput(
            wagon_type="retro" if depot == "ВРМ" else "standard",
            depot_base=depot,
            pickup_stop=pickup,
            dropoff_stop=dropoff,
            loop_wait_minutes=10,
        )
        result = calculate_tram_rental_trip(request_input)

        assert result.is_success is True, f"Failed for {pickup} -> {dropoff}: {result.error_message}"
        assert result.total_billable_km > 0
        assert result.total_motion_minutes > 0
        assert len(result.phase_2_rental.detailed_stops) >= 2

        # Check realistic speeds across all 3 phases
        for phase in [result.phase_1_dispatch, result.phase_2_rental, result.phase_3_return]:
            assert phase.distance_km > 0
            assert phase.motion_minutes > 0
            speed_kmh = phase.distance_km / (phase.motion_minutes / 60.0)
            assert 8.0 <= speed_kmh <= 32.0, (
                f"Unrealistic speed {speed_kmh:.1f} km/h on phase {phase.phase_number} ({phase.from_stop} -> {phase.to_stop})"
            )


def test_circular_rental_with_intermediate_loop() -> None:
    """Tests circular trip with mandatory intermediate loop (Starosinna -> Arcadia -> Starosinna)."""
    request_input = RentalCalculationInput(
        wagon_type="retro",
        depot_base="ВРМ",
        pickup_stop="пл. Старосінна",
        dropoff_stop="пл. Старосінна",
        intermediate_loop="Аркадія",
        loop_wait_minutes=10,
    )
    result = calculate_tram_rental_trip(request_input)

    assert result.is_success is True
    assert result.phase_2_rental.via_loop == "Аркадія"
    assert result.phase_2_rental.wait_minutes == 10
    assert result.total_wait_minutes == 10
    assert result.total_billable_km > 15.0


def test_invalid_stop_graceful_error() -> None:
    """Tests proper error handling when requesting nonexistent stops."""
    request_input = RentalCalculationInput(
        wagon_type="retro",
        depot_base="ВРМ",
        pickup_stop="Неіснуюча зупинка Марс",
        dropoff_stop="Аркадія",
    )
    with pytest.raises(ValueError) as exc_info:
        calculate_tram_rental_trip(request_input)

    assert "невідома" in str(exc_info.value).lower()
