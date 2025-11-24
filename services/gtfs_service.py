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
            cls._instance.routes_db = {}  # { "route_name": { direction_id: [ (lat, lon, stop_name), ... ] } }
            cls._instance.is_loaded = False
        return cls._instance

    def load_data(self, gtfs_folder: str = "gtfs_static_data"):
        """Завантажує та обробляє GTFS дані для побудови послідовностей зупинок."""
        if self.is_loaded:
            return

        logger.info("🔄 Починаю завантаження GTFS Static Data для побудови маршрутів...")

        try:
            # 1. Завантажуємо Stops (id -> {lat, lon, name})
            stops = {}
            with open(os.path.join(gtfs_folder, "stops.txt"), "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    stops[row["stop_id"]] = {
                        "lat": float(row["stop_lat"]),
                        "lon": float(row["stop_lon"]),
                        "name": row["stop_name"]
                    }

            # 2. Завантажуємо Routes (id -> short_name)
            # Фільтруємо тільки трамваї (0) та тролейбуси (11 або інший код, беремо всі електротранспорти)
            route_map = {}  # route_id -> route_short_name
            with open(os.path.join(gtfs_folder, "routes.txt"), "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Тут можна додати фільтр по route_type, якщо треба економити пам'ять
                    route_map[row["route_id"]] = row["route_short_name"]

            # 3. Знаходимо ОДИН Trip ID для кожного маршруту та напрямку
            # (route_short_name, direction_id) -> trip_id
            representative_trips = {}

            with open(os.path.join(gtfs_folder, "trips.txt"), "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    r_id = row["route_id"]
                    if r_id not in route_map: continue

                    r_name = route_map[r_id]
                    direction = int(row["direction_id"]) if row["direction_id"] else 0
                    key = (r_name, direction)

                    # Беремо перший ліпший trip для цього маршруту і напрямку
                    if key not in representative_trips:
                        representative_trips[key] = row["trip_id"]

            # Інвертуємо для швидкого пошуку: trip_id -> (route_name, direction)
            trip_to_route = {v: k for k, v in representative_trips.items()}

            # 4. Будуємо послідовність зупинок (Stop Times)
            # temp_sequences: { (route_name, direction) : [ (seq, stop_id), ... ] }
            temp_sequences = defaultdict(list)

            with open(os.path.join(gtfs_folder, "stop_times.txt"), "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    t_id = row["trip_id"]
                    if t_id in trip_to_route:
                        route_key = trip_to_route[t_id]  # (name, direction)
                        stop_id = row["stop_id"]
                        seq = int(row["stop_sequence"])
                        temp_sequences[route_key].append((seq, stop_id))

            # 5. Фінальна збірка
            for (r_name, direction), seq_list in temp_sequences.items():
                # Сортуємо за sequence ID
                seq_list.sort(key=lambda x: x[0])

                # Перетворюємо на список координат
                coords_sequence = []
                for _, s_id in seq_list:
                    if s_id in stops:
                        s = stops[s_id]
                        coords_sequence.append((s["lat"], s["lon"], s["name"]))

                if r_name not in self.routes_db:
                    self.routes_db[r_name] = {}
                self.routes_db[r_name][direction] = coords_sequence

            self.is_loaded = True
            logger.info(f"✅ GTFS Routes побудовано: {len(self.routes_db)} маршрутів.")

        except Exception as e:
            logger.error(f"❌ Помилка завантаження GTFS: {e}")

    def get_vehicle_status(self, route_name: str, ew_direction: int,
                           vehicle_lat: float, vehicle_lon: float,
                           user_lat: float, user_lon: float) -> str:
        """
        Визначає статус транспорту відносно користувача.
        Повертає: 'passed' (проїхав), 'arriving' (прибуває/на зупинці), 'approaching' (їде до нас), 'unknown'.
        """
        if not self.is_loaded or route_name not in self.routes_db:
            return "unknown"

        # Мапінг напрямків: EasyWay (1, 2) -> GTFS (0, 1)
        # Це евристика. Ми перевіримо обидва варіанти, якщо треба.
        # Зазвичай EW Direction 1 = GTFS 0, EW Direction 2 = GTFS 1.
        gtfs_dir = 0 if ew_direction == 1 else 1

        stops_seq = self.routes_db[route_name].get(gtfs_dir)

        # Якщо не знайшли по мапінгу, спробуємо інший напрямок (іноді буває плутанина)
        if not stops_seq:
            gtfs_dir = 1 - gtfs_dir
            stops_seq = self.routes_db[route_name].get(gtfs_dir)

        if not stops_seq:
            return "unknown"

        # 1. Знаходимо індекс зупинки КОРИСТУВАЧА у цій послідовності
        user_idx = self._find_nearest_index(stops_seq, user_lat, user_lon)

        # Якщо зупинка користувача дуже далеко від цього маршруту (напр. > 500м),
        # то, мабуть, ми вибрали неправильний напрямок (зворотній).
        if user_idx == -1:
            # Спробуємо інвертувати напрямок
            gtfs_dir = 1 - gtfs_dir
            stops_seq = self.routes_db[route_name].get(gtfs_dir)
            if stops_seq:
                user_idx = self._find_nearest_index(stops_seq, user_lat, user_lon)

        if user_idx == -1:
            return "unknown"  # Зупинка не на цьому маршруті

        # 2. Знаходимо індекс зупинки ТРАНСПОРТУ
        vehicle_idx = self._find_nearest_index(stops_seq, vehicle_lat, vehicle_lon)

        if vehicle_idx == -1:
            return "unknown"

        # 3. Порівняння
        # buffer - це кількість зупинок "похибки".
        # Якщо index однаковий, вважаємо що він "arriving".

        if vehicle_idx > user_idx:
            return "passed"  # Транспорт далі по списку, ніж ми
        elif vehicle_idx == user_idx:
            return "arriving"  # Він прямо тут
        else:
            return "approaching"  # Він ще не доїхав (індекс менше)

    def _find_nearest_index(self, sequence: List[Tuple[float, float, str]], lat: float, lon: float) -> int:
        """Знаходить індекс найближчої координат в списку."""
        best_idx = -1
        min_dist = 0.006  # ~600-700 метрів поріг. Якщо далі - це не та зупинка.

        for i, (s_lat, s_lon, _) in enumerate(sequence):
            # Евклідова відстань (спрощено, бо координати близькі)
            dist = sqrt((s_lat - lat) ** 2 + (s_lon - lon) ** 2)
            if dist < min_dist:
                min_dist = dist
                best_idx = i

        return best_idx


# Створюємо екземпляр
gtfs_service = GTFSService()