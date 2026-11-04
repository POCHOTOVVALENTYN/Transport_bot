#!/usr/bin/env python3
"""CLI utility for calculating Tram & Trolleybus rental trips and generating route sheets.

Usage:
  python3 calculate_route.py --start "пл. Старосінна" --loop "Аркадія" --end "пл. Старосінна" --pdf
  python3 calculate_route.py --transport tram --start "пл. Старосінна" --loops "Аркадія,Парк ім. Тараса Шевченка" --time 08:30
  python3 calculate_route.py --transport trolleybus --start "Залізничний вокзал" --loop "Парк ім. Тараса Шевченка" --end "вул. Архітекторська" --pdf
  python3 calculate_route.py --list-loops --transport trolleybus
"""
import argparse
import sys
from typing import List
from services.tram_rental_service import (
    RentalCalculationInput,
    calculate_tram_rental_trip,
    generate_rental_route_sheet_pdf,
    get_available_stops,
    get_available_turning_loops,
)


def run_cli() -> None:
    parser = argparse.ArgumentParser(
        description="Розрахунок кілометражу, часу (за даними Wialon) та детального маршруту оренди трамвая або тролейбуса КП «ОМЕТ»."
    )
    parser.add_argument(
        "--transport",
        type=str,
        choices=["tram", "trolleybus"],
        default="tram",
        help="Вид транспорту: tram (трамвай) або trolleybus (тролейбус)",
    )
    parser.add_argument("--start", type=str, help="Зупинка посадки пасажирів")
    parser.add_argument("--end", type=str, help="Зупинка висадки пасажирів (за замовчуванням дорівнює --start)")
    parser.add_argument("--loop", type=str, help="Проміжне розворотне кільце (обов'язкове для кільцевих маршрутів)")
    parser.add_argument(
        "--loops",
        type=str,
        help="Довільний список проміжних розворотних кілець через кому (напр. 'Аркадія,Парк ім. Тараса Шевченка')",
    )
    parser.add_argument(
        "--wagon",
        type=str,
        choices=["retro", "standard", "trolleybus"],
        default="retro",
        help="Тип рухомого складу: retro (ВРМ), standard (ТД-1 / ТД-2), trolleybus (ТрД)",
    )
    parser.add_argument(
        "--depot",
        type=str,
        choices=["ВРМ", "ТД-1", "ТД-2", "ТрД"],
        help="Пункт дислокації (за замовчуванням ВРМ для retro, ТД-1 для standard, ТрД для trolleybus)",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=10,
        help="Час регламентної стоянки на кожному розворотному кільці у хвилинах (за замовчуванням 10 хв)",
    )
    parser.add_argument(
        "--time",
        type=str,
        help="Час виїзду (ГГ:ХХ, напр. 08:30 або 17:15) для вибору профілю швидкості потоку Wialon",
    )
    parser.add_argument(
        "--day-type",
        type=str,
        choices=["workday", "weekend"],
        default="workday",
        help="Тип дня для профілю Wialon: workday (робочий) або weekend (вихідний)",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Згенерувати офіційний маршрутний лист у форматі PDF",
    )
    parser.add_argument(
        "--list-loops",
        action="store_true",
        help="Показати список усіх доступних розворотних кілець Одеси",
    )
    parser.add_argument(
        "--list-stops",
        action="store_true",
        help="Показати список усіх зупинок мережі",
    )

    args = parser.parse_args()
    vt_code = "TROLLEYBUS" if args.transport == "trolleybus" or args.wagon == "trolleybus" or args.depot == "ТрД" else "TRAM"
    vt_label = "ТРОЛЕЙБУСА" if vt_code == "TROLLEYBUS" else "ТРАМВАЯ"

    if args.list_loops:
        print(f"\n=== ДОСТУПНІ РОЗВОРОТНІ КІЛЬЦЯ {vt_label} (КП «ОМЕТ» / WIALON) ===")
        for idx, loop_name in enumerate(get_available_turning_loops(vt_code), 1):
            print(f"{idx:2d}. {loop_name}")
        return

    if args.list_stops:
        print(f"\n=== ЗУПИНКИ ТА ДЕПО МЕРЕЖІ {vt_label} (WIALON) ===")
        for idx, stop_name in enumerate(get_available_stops(vt_code), 1):
            print(f"{idx:3d}. {stop_name}")
        return

    if not args.start:
        print("Помилка: Не вказано зупинку посадки (--start). Використовуйте --help для довідки.", file=sys.stderr)
        sys.exit(1)

    dropoff = args.end or args.start
    via_loops_list: List[str] = []
    if args.loops:
        via_loops_list = [x.strip() for x in args.loops.split(",") if x.strip()]

    effective_wagon = "trolleybus" if vt_code == "TROLLEYBUS" else args.wagon

    try:
        calc_input = RentalCalculationInput(
            transport_type=vt_code,
            wagon_type=effective_wagon,
            depot_base=args.depot,
            pickup_stop=args.start,
            dropoff_stop=dropoff,
            intermediate_loop=args.loop,
            via_loops=via_loops_list,
            loop_wait_minutes=args.wait,
            departure_time=args.time,
            day_type="WEEKEND" if args.day_type == "weekend" else "WORKDAY",
        )
        res = calculate_tram_rental_trip(calc_input)
    except Exception as exc:
        print(f"\nПомилка розрахунку: {exc}", file=sys.stderr)
        sys.exit(1)

    # 1. Summary Block
    print("\n==========================================================================================")
    print("  КП «ОДЕСМІСЬКЕЛЕКТРОТРАНС» — СЛУЖБА РУХУ (ТЕЛЕМЕТРІЯ WIALON)")
    print(f"  МАРШРУТНИЙ РОЗРАХУНОК ОРЕНДИ {vt_label}")
    print("==========================================================================================")
    print(f"Номер замовлення:  {res.order_id}")
    if res.transport_type == "TROLLEYBUS":
        w_desc = "Тролейбус (БКМ / Богдан Т701)"
    elif res.wagon_type == "retro":
        w_desc = "Ретро (відкритий №914)"
    else:
        w_desc = "Стандартний (Tatra / Odissey)"
    print(f"Рухомий склад:     {w_desc}")
    print(f"База приписки:     {res.depot_base} | Профіль темпу руху: {res.time_profile}")
    print("------------------------------------------------------------------------------------------")
    print("ФІНАНСОВО-ОПЕРАТИВНИЙ ПІДСУМОК ЗА ФАЗАМИ РЕЙСУ:")
    print(f"1. Подача з депо:  {res.phase_1_dispatch.from_stop} -> {res.phase_1_dispatch.to_stop}")
    print(f"                   {res.phase_1_dispatch.distance_km:.2f} км | {res.phase_1_dispatch.motion_minutes} хв руху")

    loop_str = f" [через кільця: '{res.phase_2_rental.via_loop}']" if res.phase_2_rental.via_loop else ""
    print(f"2. Орендний рейс:  {res.phase_2_rental.from_stop} -> {res.phase_2_rental.to_stop}{loop_str}")
    print(f"                   {res.phase_2_rental.distance_km:.2f} км | {res.phase_2_rental.motion_minutes} хв руху + {res.phase_2_rental.wait_minutes} хв стоянки")

    print(f"3. Повернення:     {res.phase_3_return.from_stop} -> {res.phase_3_return.to_stop}")
    print(f"                   {res.phase_3_return.distance_km:.2f} км | {res.phase_3_return.motion_minutes} хв руху")
    print("------------------------------------------------------------------------------------------")
    print(f"РАЗОМ ДО ОПЛАТИ:   {res.total_billable_km:.2f} км (100% кілометражу оплачується замовником)")
    print(f"ЗАГАЛЬНИЙ ЧАС:     {res.formatted_total_duration} ({res.total_duration_minutes} хв)")
    print("==========================================================================================")

    # 2. Detailed Stops Itinerary (Phase 2 - Rental Run)
    print("\n------------------------------------------------------------------------------------------")
    print("  ДЕТАЛЬНИЙ ПОКРОКОВИЙ ШЛЯХ ЗУПИНОК ОРЕНДНОГО МАРШРУТУ (ФАЗА 2):")
    print("------------------------------------------------------------------------------------------")
    print(f"{'№':3s} | {'Назва зупинки':32s} | {'Роль зупинки на маршруті':36s} | {'Пробіг':8s} | {'Час':6s}")
    print("-" * 92)

    for st in res.phase_2_rental.detailed_stops:
        print(
            f"{st.seq:2d}. | {st.stop_name[:32]:32s} | {st.role[:36]:36s} | {st.cumulative_km:5.2f} км | {st.cumulative_minutes:2d} хв"
        )
    print("------------------------------------------------------------------------------------------")

    # 3. Detailed Stops Itinerary (Phase 1 & 3 - Zero runs)
    print("\n  МАРШРУТ ПОДАЧІ (ФАЗА 1):")
    p1_stops = " -> ".join([st.stop_name for st in res.phase_1_dispatch.detailed_stops])
    print(f"  {p1_stops}")

    print("\n  МАРШРУТ ПОВЕРНЕННЯ (ФАЗА 3):")
    p3_stops = " -> ".join([st.stop_name for st in res.phase_3_return.detailed_stops])
    print(f"  {p3_stops}")
    print("==========================================================================================")

    if args.pdf:
        pdf_path = generate_rental_route_sheet_pdf(res)
        print(f"\n[+] Офіційний маршрутний лист згенеровано у PDF: {pdf_path}\n")


if __name__ == "__main__":
    run_cli()
