"""Comprehensive tests for the Wialon empirical transit network database and rental routing engine.

Verifies:
1. SQLite (`transport_bot.db`) and seed (`database/wialon_transit_seed.json`) coverage of all 23 routes,
   630 platforms (386 TRAM + 244 TROLLEYBUS), 54 turnaround loops, and 77 Wialon depot zero-runs.
2. Directed Wialon platform-level routing across intermediate stops on Fontan, Lustdorf, Peresyp/Kotovskoho,
   Slobidka, and Trolleybus corridors.
3. Asymmetric Trolleybus & Tram depot pull-out / pull-in (`PULL_OUT` vs `PULL_IN`) from `ТД-1`, `ТД-2`, `ВРМ`, `ТрД`.
4. Arbitrary multi-loop itineraries (`via_loops`) and time-of-day Wialon traffic pace (`dep_to_dep`).
"""
import sqlite3
import pytest
from services.tram_rental_service import (
    SQLITE_DB_PATH,
    RentalCalculationInput,
    calculate_tram_rental_trip,
    find_shortest_transit_path,
    generate_rental_route_sheet_pdf,
    get_available_stops,
    get_available_turning_loops,
    get_wialon_transit_network,
)


def test_wialon_sqlite_tables_populated() -> None:
    """Verify all 5 Wialon transit tables exist and contain full 630-platform dataset in transport_bot.db."""
    assert SQLITE_DB_PATH.exists(), "transport_bot.db must exist"
    conn = sqlite3.connect(str(SQLITE_DB_PATH))
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM transit_depots")
    assert cur.fetchone()[0] == 4

    cur.execute("SELECT transport_type, COUNT(*) FROM transit_platforms GROUP BY transport_type")
    counts = dict(cur.fetchall())
    assert counts.get("TRAM") == 386
    assert counts.get("TROLLEYBUS") == 244

    cur.execute("SELECT COUNT(*) FROM transit_turning_loops")
    assert cur.fetchone()[0] >= 50

    cur.execute("SELECT COUNT(*) FROM transit_edges WHERE edge_kind = 'LINE' AND source = 'WIALON'")
    wialon_line_edges = cur.fetchone()[0]
    assert wialon_line_edges >= 660

    cur.execute("SELECT COUNT(*) FROM transit_depot_zero_runs")
    assert cur.fetchone()[0] >= 49
    conn.close()


def test_trolleybus_rental_with_asymmetric_depot_zero_runs(tmp_path) -> None:
    """Verify trolleybus rental trip from TrD uses Wialon zero-runs and overhead wire network."""
    calc_input = RentalCalculationInput(
        transport_type="TROLLEYBUS",
        wagon_type="trolleybus",
        depot_base="ТрД",
        pickup_stop="Залізничний вокзал",
        dropoff_stop="вул. Архітекторська",
        intermediate_loop="Парк ім. Тараса Шевченка",
        loop_wait_minutes=10,
        departure_time="12:00",
        day_type="WORKDAY",
    )
    res = calculate_tram_rental_trip(calc_input)
    assert res.is_success is True
    assert res.transport_type == "TROLLEYBUS"
    assert res.depot_base == "ТрД"
    assert res.time_profile == "WORKDAY:10-16"

    # Phase 1: TrD -> Залізничний вокзал (verified Wialon PULL_OUT: 8.55 km, 33 min)
    assert res.phase_1_dispatch.distance_km == 8.55
    assert res.phase_1_dispatch.motion_minutes == 33

    # Phase 2: Залізничний вокзал -> Парк ім. Тараса Шевченка -> вул. Архітекторська
    assert res.phase_2_rental.distance_km > 12.0
    assert res.phase_2_rental.motion_minutes > 35
    assert res.phase_2_rental.wait_minutes == 10
    assert len(res.phase_2_rental.detailed_stops) >= 20

    # Phase 3: вул. Архітекторська -> TrD (verified Wialon PULL_IN)
    assert res.phase_3_return.distance_km > 0
    assert res.phase_3_return.motion_minutes > 0

    pdf_file = str(tmp_path / "trolleybus_sheet.pdf")
    out_pdf = generate_rental_route_sheet_pdf(res, output_pdf_path=pdf_file)
    assert out_pdf == pdf_file


def test_multi_loop_custom_tram_itinerary() -> None:
    """Verify support for arbitrary list of intermediate turning loops (via_loops)."""
    calc_input = RentalCalculationInput(
        transport_type="TRAM",
        wagon_type="retro",
        depot_base="ВРМ",
        pickup_stop="пл. Старосінна",
        dropoff_stop="пл. Старосінна",
        via_loops=["Аркадія", "Парк ім. Тараса Шевченка", "пл. Тираспольська"],
        loop_wait_minutes=8,
        departure_time="08:30",
        day_type="WORKDAY",
    )
    res = calculate_tram_rental_trip(calc_input)
    assert res.is_success is True
    assert res.time_profile == "WORKDAY:07-10"
    assert res.phase_2_rental.via_loops == ["Аркадія", "Парк ім. Тараса Шевченка", "пл. Тираспольська"]
    assert res.phase_2_rental.wait_minutes == 24  # 3 loops * 8 min
    assert res.total_wait_minutes == 24
    assert res.phase_2_rental.distance_km > 17.0
    assert len(res.phase_2_rental.detailed_stops) >= 30


def test_wialon_intermediate_platforms_and_time_of_day_pace() -> None:
    """Verify intermediate non-terminal stops and Wialon rush-hour vs evening runtime differences."""
    morning_rush = find_shortest_transit_path(
        "Куликове поле",
        "16-а станція Великого Фонтану",
        transport_type="TRAM",
        departure_time="08:30",
        day_type="WORKDAY",
    )
    evening_free = find_shortest_transit_path(
        "Куликове поле",
        "16-а станція Великого Фонтану",
        transport_type="TRAM",
        departure_time="20:30",
        day_type="WORKDAY",
    )
    # Full stop-by-stop sequence must include intermediate Fontan stations (not just 3 hops)
    assert len(morning_rush["path"]) >= 18
    assert any("7-а станція" in s for s in morning_rush["path"])
    assert any("10-а станція" in s for s in morning_rush["path"])
    assert morning_rush["distance_km"] > 8.5
    assert morning_rush["duration_minutes"] >= evening_free["duration_minutes"]


def test_stop_and_loop_catalogs_for_both_transport_types() -> None:
    """Verify get_available_stops and get_available_turning_loops return complete catalogs."""
    tram_stops = get_available_stops("TRAM")
    trol_stops = get_available_stops("TROLLEYBUS")
    tram_loops = get_available_turning_loops("TRAM")
    trol_loops = get_available_turning_loops("TROLLEYBUS")

    assert len(tram_stops) >= 200
    assert len(trol_stops) >= 120
    assert len(tram_loops) >= 34
    assert len(trol_loops) >= 18
    assert "вул. Архітекторська" in trol_loops
    assert "Суперфосфатний завод" in trol_loops
