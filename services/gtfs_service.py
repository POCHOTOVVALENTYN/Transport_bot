# services/gtfs_service.py
import csv
import logging
import os
from collections import defaultdict
from math import sqrt
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger("transport_bot")


class GTFSService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GTFSService, cls).__new__(cls)
            # Структура: { ("10", "tram"): [ [stop1, stop2...], [stopA, stopB...] ] }
            # Ми зберігаємо список усіх можливих послідовностей зупинок для маршруту
            cls._instance.routes_db = defaultdict(list)
            cls._instance.is_loaded = False
        return cls._instance

    def load_data(self, gtfs_folder: str = "gtfs_static_data"):
        """
        Завантажує GTFS.
        Логіка: Зберігаємо всі унікальні геометрії маршрутів, ігноруємо direction_id.
        """
        if self.is_loaded: return

        logger.info("🔄 Починаю завантаження GTFS (Robust Mode)...")

        try:
            # 1. Stops
            stops = {}
            with open(os.path.join(gtfs_folder, "stops.txt"), "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    stops[row["stop_id"]] = {
                        "lat": float(row["stop_lat"]),
                        "lon": float(row["stop_lon"]),
                        "name": row["stop_name"]
                    }

            # 2. Routes -> Мапимо ID на (Ім'я, Тип)
            valid_types_map = {'0': 'tram', '11': 'trol', '900': 'tram', '800': 'trol'}
            route_info = {}

            with open(os.path.join(gtfs_folder, "routes.txt"), "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    r_type = row.get("route_type", "3")
                    if r_type not in valid_types_map: continue

                    # Фільтр для маршруток, що прикидаються трамваями (Пересипський міст і т.д.)
                    r_long = row.get("route_long_name", "").lower()
                    r_name = row["route_short_name"]

                    if r_name == "10" and ("пересып" in r_long or "пересип" in r_long):
                        continue  # Пропускаємо маршрутку №10

                    route_info[row["route_id"]] = {
                        "name": r_name,
                        "type": valid_types_map[r_type]
                    }

            # 3. Trips -> Групуємо trips по route_id
            # Ми беремо по одному найдовшому trip для кожного route_id
            # (бо в Одесі route_id 107600 і 107601 - це різні напрямки одного трамвая)
            trips_by_route_id = defaultdict(list)

            with open(os.path.join(gtfs_folder, "trips.txt"), "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row["route_id"] in route_info:
                        trips_by_route_id[row["route_id"]].append(row["trip_id"])

            # 4. Stop Times -> Рахуємо
            trip_stops_data = defaultdict(list)
            trip_lengths = defaultdict(int)

            with open(os.path.join(gtfs_folder, "stop_times.txt"), "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    t_id = row["trip_id"]
                    # Оптимізація: зберігаємо тільки якщо це релевантний trip (можна пропустити перевірку для швидкості)
                    trip_stops_data[t_id].append((int(row["stop_sequence"]), row["stop_id"]))
                    trip_lengths[t_id] += 1

            # 5. Збірка фінальної бази
            count_seqs = 0

            # Для кожного унікального route_id (наприклад 107600, 107601)
            for r_id, t_ids in trips_by_route_id.items():
                # Знаходимо trip з максимальною кількістю зупинок для цього route_id
                best_trip = None
                max_len = -1

                for t_id in t_ids:
                    if trip_lengths.get(t_id, 0) > max_len:
                        max_len = trip_lengths[t_id]
                        best_trip = t_id

                if best_trip and best_trip in trip_stops_data:
                    # Будуємо послідовність
                    raw_seq = sorted(trip_stops_data[best_trip], key=lambda x: x[0])

                    coords_seq = []
                    for _, s_id in raw_seq:
                        if s_id in stops:
                            s = stops[s_id]
                            coords_seq.append((s["lat"], s["lon"], s["name"]))

                    if coords_seq:
                        info = route_info[r_id]
                        db_key = (info["name"], info["type"])  # ('10', 'tram')

                        # Додаємо цю послідовність у список варіантів для маршруту
                        self.routes_db[db_key].append(coords_seq)
                        count_seqs += 1

            self.is_loaded = True
            logger.info(f"✅ GTFS Loaded. Built {count_seqs} unique route sequences.")

        except Exception as e:
            logger.error(f"❌ GTFS Error: {e}", exc_info=True)

    def get_closest_stop_name(self, route_name: str, transport_type: str, ew_direction: int, lat: float, lon: float) -> \
    Optional[str]:
        """
        Шукає найближчу зупинку.
        ПОВЕРТАЄ None, якщо вагон занадто далеко від маршруту (> 500м).
        Це фільтрує сміття з інших маршрутів.
        """
        if not self.is_loaded: return None

        route_name = str(route_name).strip()
        if 'trol' in transport_type:
            transport_type = 'trol'
        elif 'tram' in transport_type:
            transport_type = 'tram'

        db_key = (route_name, transport_type)

        if db_key not in self.routes_db:
            # Fallback
            if (route_name, 'tram') in self.routes_db:
                db_key = (route_name, 'tram')
            elif (route_name, 'trol') in self.routes_db:
                db_key = (route_name, 'trol')
            else:
                return None

        all_sequences = self.routes_db[db_key]

        best_stop_name = None
        global_min_dist = float('inf')

        # Перебираємо всі варіанти руху
        for seq in all_sequences:
            idx, dist = self._find_nearest_in_seq(seq, lat, lon)
            if idx != -1 and dist < global_min_dist:
                global_min_dist = dist
                best_stop_name = seq[idx][2]

        # === ГОЛОВНА ЗМІНА: ФІЛЬТР ВІДСТАНІ ===
        # 0.005 градусів ~= 500-600 метрів.
        # Якщо найближча зупинка далі, значить вагон не на цьому маршруті.
        MAX_DISTANCE_THRESHOLD = 0.005

        if best_stop_name and global_min_dist <= MAX_DISTANCE_THRESHOLD:
            return best_stop_name

        # Якщо далеко - повертаємо None, щоб хендлер його приховав
        return None

    def _find_nearest_in_seq(self, sequence: List[Tuple[float, float, str]], lat: float, lon: float) -> Tuple[
        int, float]:
        best_idx = -1
        min_dist = float('inf')

        for i, (s_lat, s_lon, _) in enumerate(sequence):
            # Евклідова відстань
            dist = sqrt((s_lat - lat) ** 2 + (s_lon - lon) ** 2)
            if dist < min_dist:
                min_dist = dist
                best_idx = i

        return best_idx, min_dist


gtfs_service = GTFSService()