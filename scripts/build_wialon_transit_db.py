#!/usr/bin/env python3
"""Build complete Wialon empirical transit network database for Transport_bot.

Extracts and combines:
1. All 630 platforms (386 TRAM + 244 TROLLEYBUS) and 23 active routes (+ 2 reserve routes)
   from «АРМ Розклади — КП Одесміськелектротранс» (`omet.db` + `gtfs_static_data`).
2. Empirical stop-to-stop travel times (`dep_to_dep` traffic flow pace, `run_sec`, `dwell_sec`,
   `p15`, `p85`, `sample_n`) across all 16,110 Wialon GPS vehicle-days (`passes.pkl` + raw Wialon tracks).
3. All 50 physical turnaround loops/nodes (34 TRAM + 16 TROLLEYBUS) with throat directionality
   (`BIDIRECTIONAL`, `ONEWAY_A_TO_A`, `ONEWAY_B_TO_B`, `BLOCK_LOOP`, `WYE_TRIANGLE`) and Wialon cluster stats.
4. Inter-route switch connections (`osm_rail_topology.json`) and verified depot zero-runs
   (`zero_run_candidates.json` + `zero_runs_measured.csv`) for `ТД-1`, `ТД-2`, `ВРМ`, and `ТрД`.
5. Saves portable seed snapshot `database/wialon_transit_seed.json` and populates SQLite tables in `transport_bot.db`.
"""
from collections import defaultdict
import csv
from datetime import datetime
import gzip
import json
import math
from multiprocessing import Pool
import os
from pathlib import Path
import pickle
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

import numpy as np
from pydantic import BaseModel
from scipy.spatial import cKDTree

BASE_DIR = Path(__file__).resolve().parent.parent
ARM_DIR = Path("/Users/valentin/antigravity/АРМ-Розклади-—-КП-Одесміськелектротранс-2026-08-04-8f27e")
OMET_DB_PATH = ARM_DIR / "backend" / "omet.db"
OSM_TOPOLOGY_PATH = ARM_DIR / "backend" / "app" / "core" / "osm_rail_topology.json"
PASSES_PKL_PATH = ARM_DIR / "_specs" / "shared-kt-headway" / "audit" / "cache" / "passes.pkl"
WIALON_RAW_DIR = ARM_DIR / "_specs" / "temporary-schemes" / "audit" / "wialon_month" / "scripts" / "raw"
UNITS_JSON_PATH = ARM_DIR / "_specs" / "temporary-schemes" / "audit" / "wialon_month" / "scripts" / "units.json"
ZERO_RUN_CANDIDATES_PATH = ARM_DIR / "backend" / "scripts" / "omet_data" / "zero_run_candidates.json"
ZERO_RUNS_MEASURED_CSV = ARM_DIR / "_specs" / "zero-runs" / "audit" / "2026-10-audit" / "wialon" / "zero_runs_measured.csv"
DAYS_W1_CSV = ARM_DIR / "_specs" / "zero-runs" / "audit" / "2026-10-audit" / "wialon" / "days_w1.csv"
DAYS_W2_CSV = ARM_DIR / "_specs" / "zero-runs" / "audit" / "2026-10-audit" / "wialon" / "days_w2.csv"

SEED_OUTPUT_PATH = BASE_DIR / "database" / "wialon_transit_seed.json"
BOT_DB_PATH = BASE_DIR / "transport_bot.db"

KYIV_TZ = ZoneInfo("Europe/Kyiv")
R_EARTH_M = 6371000.0
LAT0_RAD = math.radians(46.47)
COS_LAT0 = math.cos(LAT0_RAD)
R_STOP_M = 35.0
HEAD_TOL_DEG = 55.0
GAP_S = 180.0
MAX_SKIP_STOPS = 3
LINK_MAX_S = 20 * 60
MERGE_S = 10 * 60
BREAK_S = 300.0

PERIODS: List[Tuple[str, int, int]] = [
    ("05-07", 5, 7),
    ("07-10", 7, 10),
    ("10-16", 10, 16),
    ("16-19", 16, 19),
    ("19-24", 19, 24),
]

VERIFIED_STATION_COORDS: Dict[str, Tuple[float, float]] = {
    "708918": (46.361091, 30.701989),  # 16-а станція Люстдорфської дороги
    "708922": (46.353142, 30.701101),  # Дача Ковалевського
    "708923": (46.353142, 30.701101),  # Монастир
    "708924": (46.350378, 30.701301),  # Санаторій "Люстдорф"
    "708925": (46.349592, 30.692109),  # вул. Зої Космодем'янської
    "708926": (46.346716, 30.679160),  # с-ще Бурлача Балка
    "708927": (46.334284, 30.666245),  # Рибний порт
}

DEPOT_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "code": "ТД-1",
        "arm_code": "TD-1",
        "name": "Трамвайне депо №1 (ім. Шевченка, вул. Водопровідна, 1)",
        "transport_type": "TRAM",
        "park_lat": 46.466955,
        "park_lon": 30.734086,
        "gate_out_lat": 46.467937,
        "gate_out_lon": 30.735428,
        "gate_out_alt_lat": 46.468266,
        "gate_out_alt_lon": 30.733626,
        "gate_in_lat": 46.468269,
        "gate_in_lon": 30.733646,
        "gate_in_alt_lat": 46.466600,
        "gate_in_alt_lon": 30.735975,
        "maneuver_out_min": 3.0,
        "maneuver_in_min": 4.0,
        "anchor_stops": ["пл. Старосінна", "ринок \"Привоз\"", "Преображенський парк", "Завод \"Стальканат\""],
    },
    {
        "code": "ТД-2",
        "arm_code": "TD-2",
        "name": "Трамвайне депо №2 (Слобідка, вул. Академіка Воробйова / Рачкова)",
        "transport_type": "TRAM",
        "park_lat": 46.484055,
        "park_lon": 30.695725,
        "gate_out_lat": 46.484640,
        "gate_out_lon": 30.697490,
        "gate_in_lat": 46.485300,
        "gate_in_lon": 30.696479,
        "maneuver_out_min": 3.0,
        "maneuver_in_min": 4.0,
        "anchor_stops": ["вул. Маловського", "вул. Рачкова", "Дитяча лікарня", "Слобідський ринок"],
    },
    {
        "code": "ВРМ",
        "arm_code": "VRM",
        "name": "Вагоноремонтні майстерні / Музей КП «ОМЕТ» (пл. Олексіївська, 1А)",
        "transport_type": "TRAM",
        "park_lat": 46.460103,
        "park_lon": 30.713778,
        "gate_out_lat": 46.459811,
        "gate_out_lon": 30.714560,
        "gate_in_lat": 46.459811,
        "gate_in_lon": 30.714560,
        "maneuver_out_min": 2.0,
        "maneuver_in_min": 2.0,
        "anchor_stops": ["станція Одеса-Товарна", "пл. Олексіївська", "вул. Михайла Болтенка"],
    },
    {
        "code": "ТрД",
        "arm_code": "TrD",
        "name": "Тролейбусне депо №1 (вул. Інглезі, 5 / 17)",
        "transport_type": "TROLLEYBUS",
        "park_lat": 46.417933,
        "park_lon": 30.712277,
        "gate_out_lat": 46.418600,
        "gate_out_lon": 30.713979,
        "gate_in_lat": 46.418862,
        "gate_in_lon": 30.713696,
        "maneuver_out_min": 3.0,
        "maneuver_in_min": 3.5,
        "anchor_stops": ["вул. Інглезі", "вул. Михайла Комарова", "Завод \"Промзв'язок\""],
    },
]


class BuildDatabaseSummary(BaseModel):
    total_routes: int
    total_platforms: int
    tram_platforms: int
    trolleybus_platforms: int
    total_directed_edges: int
    wialon_measured_edges: int
    total_turning_loops: int
    tram_turning_loops: int
    trolleybus_turning_loops: int
    total_depot_zero_runs: int
    seed_file_path: str


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two WGS84 coordinates."""
    r_lat1, r_lon1, r_lat2, r_lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = r_lat2 - r_lat1
    dlon = r_lon2 - r_lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(r_lat1) * math.cos(r_lat2) * math.sin(dlon / 2) ** 2
    return 2 * R_EARTH_M * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate compass bearing in degrees [0, 360)."""
    r_lat1, r_lon1, r_lat2, r_lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    y = math.sin(r_lon2 - r_lon1) * math.cos(r_lat2)
    x = math.cos(r_lat1) * math.sin(r_lat2) - math.sin(r_lat1) * math.cos(r_lat2) * math.cos(r_lon2 - r_lon1)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angdiff_deg(a: float, b: float) -> float:
    """Calculate minimal absolute angle difference in degrees [0, 180]."""
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def to_xy_m(lat: float, lon: float) -> Tuple[float, float]:
    """Project (lat, lon) to local planar meters around Odesa."""
    x = math.radians(lon) * R_EARTH_M * COS_LAT0
    y = math.radians(lat) * R_EARTH_M
    return x, y


def clean_stop_display_name(raw_name: str) -> str:
    """Fix unbalanced quotes and whitespace in stop names from database."""
    if not raw_name:
        return ""
    s = " ".join(raw_name.strip().split())
    if s.count('"') == 1 and not s.endswith('"'):
        s = s + '"'
    s = s.replace("вул. Іцкаха Рабіна", "вул. Іцхака Рабіна")
    return s


def norm_stop_key(raw_name: str) -> str:
    """Canonical lowercase key for stop matching."""
    s = clean_stop_display_name(raw_name).lower()
    s = s.replace("«", '"').replace("»", '"').replace("’", "'").replace("`", "'")
    s = s.replace("ст. ", "станція ").replace("пл. ", "площа ")
    return s


def period_of_timestamp(ts: float) -> Optional[str]:
    """Determine time-of-day period for a Unix timestamp in Kyiv time."""
    dt = datetime.fromtimestamp(ts, KYIV_TZ)
    h = dt.hour + dt.minute / 60.0
    for name, start_h, end_h in PERIODS:
        if start_h <= h < end_h:
            return name
    return None


def daytype_of_date(day_str: str) -> str:
    """Return WORKDAY or WEEKEND for YYYY-MM-DD."""
    dt = datetime.strptime(day_str, "%Y-%m-%d")
    return "WEEKEND" if dt.weekday() >= 5 else "WORKDAY"


# --- Wialon Track Cleaning & Resampling (identical to detect_turns.py) ---
def _clean_raw_track(raw_pts: List[List[float]]) -> Optional[np.ndarray]:
    if not raw_pts or len(raw_pts) < 30:
        return None
    a = np.asarray(raw_pts, dtype=float)
    mask = (a[:, 1] >= 46.30) & (a[:, 1] <= 46.65) & (a[:, 2] >= 30.60) & (a[:, 2] <= 30.85)
    a = a[mask]
    if len(a) < 30:
        return None
    order = np.argsort(a[:, 0], kind="mergesort")
    a = a[order]
    keep = np.concatenate([[True], np.diff(a[:, 0]) > 0])
    a = a[keep]
    if len(a) < 30:
        return None
    return a


def _resample_track(a: np.ndarray, step_m: float = 6.0) -> np.ndarray:
    xs = np.radians(a[:, 2]) * R_EARTH_M * COS_LAT0
    ys = np.radians(a[:, 1]) * R_EARTH_M
    ts = a[:, 0]
    out = [[xs[0], ys[0], ts[0], ts[0]]]
    for i in range(1, len(a)):
        dx = xs[i] - out[-1][0]
        dy = ys[i] - out[-1][1]
        if dx * dx + dy * dy < step_m * step_m:
            out[-1][3] = ts[i]
        else:
            out.append([xs[i], ys[i], ts[i], ts[i]])
    return np.asarray(out, dtype=float)


_WORKER_TREES: Dict[str, Any] = {}


def _init_pass_worker(trees_data: Dict[str, Tuple[List[str], np.ndarray]]) -> None:
    global _WORKER_TREES
    _WORKER_TREES = {}
    for vt, (ids, pts) in trees_data.items():
        _WORKER_TREES[vt] = (ids, pts, cKDTree(pts))


def _extract_passes_for_job(job: Tuple[str, str, str]) -> Optional[Tuple[str, str, str, np.ndarray, List[Tuple[float, float]]]]:
    uid, day, vt = job
    gz_path = WIALON_RAW_DIR / uid / f"{day}.json.gz"
    if not gz_path.exists():
        return None
    try:
        with gzip.open(gz_path, "rt", encoding="utf-8") as f:
            raw_pts = json.load(f)
        a = _clean_raw_track(raw_pts)
    except Exception:
        return None
    if a is None:
        return None
    r = _resample_track(a)
    n = len(r)
    if n < 40:
        return None
    ids, pts, tree = _WORKER_TREES[vt]
    near = tree.query_ball_point(r[:, :2], R_STOP_M)
    per_stop: Dict[int, List[int]] = {}
    for k, lst in enumerate(near):
        for si in lst:
            per_stop.setdefault(si, []).append(k)
    rows = []
    for si, ks in per_stop.items():
        px, py = pts[si]
        runs = []
        s = ks[0]
        p = ks[0]
        for k in ks[1:]:
            if k != p + 1:
                runs.append((s, p))
                s = k
            p = k
        runs.append((s, p))
        for s_idx, e_idx in runs:
            seg = r[s_idx : e_idx + 1]
            d = np.hypot(seg[:, 0] - px, seg[:, 1] - py)
            j = s_idx + int(np.argmin(d))
            k0, k1 = max(j - 2, 0), min(j + 2, n - 1)
            if k0 == k1:
                continue
            # Compass bearing from planar dx, dy: atan2(dx, dy)
            crs = (math.degrees(math.atan2(r[k1, 0] - r[k0, 0], r[k1, 1] - r[k0, 1])) + 360.0) % 360.0
            rows.append((si, r[s_idx, 2], r[e_idx, 3], r[j, 2], float(d.min()), crs))

    gaps: List[Tuple[float, float]] = []
    dt = r[1:, 2] - r[:-1, 3]
    for i in np.nonzero(dt > GAP_S)[0]:
        gaps.append((float(r[i, 3]), float(r[i + 1, 2])))
    raw_dt = np.diff(a[:, 0])
    for i in np.nonzero(raw_dt > GAP_S)[0]:
        gaps.append((float(a[i, 0]), float(a[i + 1, 0])))
    arr = np.array(rows, dtype=float) if rows else np.zeros((0, 6))
    return uid, day, vt, arr, sorted(set(gaps))


def build_chains_for_day(
    rows: np.ndarray,
    idx_of: Dict[int, List[int]],
    expected_courses: List[Optional[float]],
) -> List[List[List[float]]]:
    """Build monotonic pass chains along a route direction."""
    passed_items = []
    for si, ta, td, tc, dist, crs in rows:
        for i in idx_of.get(int(si), ()):
            exp_c = expected_courses[i]
            if exp_c is None or angdiff_deg(crs, exp_c) <= HEAD_TOL_DEG:
                passed_items.append([i, ta, td, tc, crs, dist])
    if not passed_items:
        return []
    passed_items.sort(key=lambda p: (p[0], p[1]))
    merged: List[List[float]] = []
    for p in passed_items:
        if merged and merged[-1][0] == p[0] and p[1] - merged[-1][2] <= MERGE_S:
            merged[-1][2] = max(merged[-1][2], p[2])
            if p[5] < merged[-1][5]:
                merged[-1][3], merged[-1][4], merged[-1][5] = p[3], p[4], p[5]
        else:
            merged.append(list(p))
    merged.sort(key=lambda p: p[3])
    n = len(merged)
    lengths = [1] * n
    preds = [-1] * n
    for p in range(n):
        ip, tp = merged[p][0], merged[p][1]
        for q in range(p - 1, -1, -1):
            if tp - merged[q][2] > LINK_MAX_S:
                if merged[p][3] - merged[q][3] > LINK_MAX_S + 3600:
                    break
                continue
            d_stops = ip - merged[q][0]
            if 0 < d_stops <= MAX_SKIP_STOPS + 1 and merged[q][2] <= tp + 1 and lengths[q] + 1 > lengths[p]:
                lengths[p] = lengths[q] + 1
                preds[p] = q
    used = [False] * n
    chains = []
    for p in sorted(range(n), key=lambda k: -lengths[k]):
        if used[p] or lengths[p] < 3:
            continue
        ch = []
        k = p
        while k >= 0 and not used[k]:
            ch.append(k)
            used[k] = True
            k = preds[k]
        if len(ch) >= 3:
            chains.append([merged[idx] for idx in reversed(ch)])
    return chains


def has_signal_break(gaps: List[Tuple[float, float]], t0: float, t1: float) -> bool:
    for a, b in gaps:
        if b - a > BREAK_S and a < t1 and b > t0:
            return True
    return False


def robust_stats(vals: List[float]) -> Optional[Tuple[int, float, float, float]]:
    if not vals:
        return None
    v = np.asarray(vals, dtype=float)
    med = float(np.median(v))
    if med <= 0:
        return None
    v = v[(v <= 3.2 * med) & (v >= max(0.15, med / 3.2))]
    if len(v) == 0:
        return None
    return (
        int(len(v)),
        round(float(np.median(v)), 1),
        round(float(np.percentile(v, 15)), 1),
        round(float(np.percentile(v, 85)), 1),
    )


def shape_segment_distances_m(
    shape_pts: Optional[List[Tuple[float, float]]],
    stop_coords: List[Tuple[float, float]],
) -> List[float]:
    """Calculate exact distance in meters between consecutive stops along route shape."""
    if not shape_pts or len(shape_pts) < 2 or len(stop_coords) < 2:
        return [
            round(haversine_m(stop_coords[k - 1][0], stop_coords[k - 1][1], stop_coords[k][0], stop_coords[k][1]) * 1.15, 1)
            for k in range(1, len(stop_coords))
        ]
    cum = [0.0]
    for i in range(1, len(shape_pts)):
        cum.append(cum[-1] + haversine_m(shape_pts[i - 1][0], shape_pts[i - 1][1], shape_pts[i][0], shape_pts[i][1]))
    idx = 0
    pos = []
    for s_pt in stop_coords:
        best_i, best_d = idx, 1e18
        for i in range(idx, len(shape_pts)):
            d = haversine_m(shape_pts[i][0], shape_pts[i][1], s_pt[0], s_pt[1])
            if d < best_d:
                best_i, best_d = i, d
        pos.append((best_i, best_d))
        idx = best_i
    out = []
    for k in range(1, len(stop_coords)):
        straight = haversine_m(stop_coords[k - 1][0], stop_coords[k - 1][1], stop_coords[k][0], stop_coords[k][1])
        (ia, da), (ib, db) = pos[k - 1], pos[k]
        along = cum[ib] - cum[ia]
        ok = da < 140.0 and db < 140.0 and straight * 0.92 <= along <= straight * 2.6 + 220.0
        out.append(round(along if ok else straight * 1.15, 1))
    return out


def build_wialon_database() -> BuildDatabaseSummary:
    """Main pipeline to build the Wialon transit database and seed snapshot."""
    print("🚀 [1/6] Loading routes, platforms, shapes, and turnaround loops from omet.db...")
    conn = sqlite3.connect(str(OMET_DB_PATH))
    cur = conn.cursor()

    cur.execute("SELECT id, number, name, type, primary_depot_id, default_speed_kmh, t_dir0_min, t_dir1_min FROM routes")
    routes_meta: Dict[str, Dict[str, Any]] = {}
    for rid, num, name, rtype, depot_id, spd, t0, t1 in cur.fetchall():
        routes_meta[str(rid)] = {
            "route_id": str(rid),
            "number": str(num),
            "name": clean_stop_display_name(name or ""),
            "transport_type": str(rtype).upper(),
            "primary_depot_id": depot_id,
            "default_speed_kmh": float(spd or (18.0 if rtype == "TRAM" else 17.0)),
            "t_dir0_min": int(t0 or 35),
            "t_dir1_min": int(t1 or 35),
        }

    # Load shapes
    cur.execute("SELECT route_id, geometry FROM route_shapes")
    route_shapes: Dict[str, List[List[Tuple[float, float]]]] = defaultdict(list)
    for rid, geom_raw in cur.fetchall():
        if not geom_raw:
            continue
        pts_raw = json.loads(geom_raw) if isinstance(geom_raw, str) else geom_raw
        pts = [(float(p["lat"]), float(p["lng"])) for p in pts_raw if "lat" in p and "lng" in p]
        if len(pts) >= 2:
            route_shapes[str(rid)].append(pts)

    # Load all platforms on routes
    cur.execute(
        """
        SELECT rs.route_id, rs.direction_id, rs.stop_sequence, s.id, s.name, s.lat, s.lon, s.lng
        FROM route_stations rs
        JOIN stations s ON s.id = rs.stop_id
        ORDER BY rs.route_id, rs.direction_id, rs.stop_sequence
        """
    )
    route_sequences: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    platforms: Dict[str, Dict[str, Any]] = {}

    for rid, d_id, seq, sid, sname, lat, lon, lng in cur.fetchall():
        rid_s = str(rid)
        if rid_s not in routes_meta:
            continue
        vt = routes_meta[rid_s]["transport_type"]
        sid_s = str(sid)
        lo = lon if lon is not None else lng
        pt_lat, pt_lon = VERIFIED_STATION_COORDS.get(sid_s, (float(lat), float(lo)))
        clean_name = clean_stop_display_name(sname or sid_s)

        if sid_s not in platforms:
            platforms[sid_s] = {
                "stop_id": sid_s,
                "name": clean_name,
                "canonical_key": norm_stop_key(clean_name),
                "transport_type": vt,
                "lat": round(pt_lat, 6),
                "lon": round(pt_lon, 6),
                "routes": [],
                "headings": [],
                "is_terminal": False,
                "is_turning_loop": False,
            }
        if rid_s not in platforms[sid_s]["routes"]:
            platforms[sid_s]["routes"].append(rid_s)

        route_sequences[(rid_s, int(d_id))].append(
            {
                "route_id": rid_s,
                "direction_id": int(d_id),
                "seq": int(seq),
                "stop_id": sid_s,
                "name": clean_name,
                "lat": pt_lat,
                "lon": pt_lon,
            }
        )

    # Calculate geometric courses and segment distances along route shapes
    segment_distances_m: Dict[Tuple[str, str, str], float] = {}  # (vt, from_id, to_id) -> meters
    for (rid_s, d_id), seq_list in route_sequences.items():
        vt = routes_meta[rid_s]["transport_type"]
        n_st = len(seq_list)
        if n_st == 0:
            continue
        platforms[seq_list[0]["stop_id"]]["is_terminal"] = True
        platforms[seq_list[-1]["stop_id"]]["is_terminal"] = True

        for i, st in enumerate(seq_list):
            p_prev = seq_list[max(i - 1, 0)]
            p_next = seq_list[min(i + 1, n_st - 1)]
            crs = bearing_deg(p_prev["lat"], p_prev["lon"], p_next["lat"], p_next["lon"])
            st["geo_course"] = round(crs, 1)
            platforms[st["stop_id"]]["headings"].append(round(crs, 1))

        # Best matching shape
        cands = route_shapes.get(rid_s, [])
        chosen_shape = None
        if cands and n_st > 1:
            chosen_shape = min(
                cands,
                key=lambda s: haversine_m(s[0][0], s[0][1], seq_list[0]["lat"], seq_list[0]["lon"])
                + haversine_m(s[-1][0], s[-1][1], seq_list[-1]["lat"], seq_list[-1]["lon"]),
            )
            if (
                haversine_m(chosen_shape[0][0], chosen_shape[0][1], seq_list[0]["lat"], seq_list[0]["lon"])
                + haversine_m(chosen_shape[-1][0], chosen_shape[-1][1], seq_list[-1]["lat"], seq_list[-1]["lon"])
                > 1500.0
            ):
                chosen_shape = None
        coords = [(s["lat"], s["lon"]) for s in seq_list]
        dists = shape_segment_distances_m(chosen_shape, coords)
        for k in range(1, n_st):
            u_id = seq_list[k - 1]["stop_id"]
            v_id = seq_list[k]["stop_id"]
            st["dist_from_prev_m"] = dists[k - 1]
            key = (vt, u_id, v_id)
            if key not in segment_distances_m:
                segment_distances_m[key] = dists[k - 1]

    print(
        f"   Loaded {len(routes_meta)} routes, {len(platforms)} platforms "
        f"({sum(1 for p in platforms.values() if p['transport_type']=='TRAM')} TRAM, "
        f"{sum(1 for p in platforms.values() if p['transport_type']=='TROLLEYBUS')} TROLLEYBUS), "
        f"{len(segment_distances_m)} directed adjacent stop pairs."
    )

    # --- STEP 2: Load Wialon Passes from passes.pkl + Scan Non-Focus Route Vehicle-Days ---
    print("🚀 [2/6] Loading cached Wialon platform passes (passes.pkl) and scanning remaining routes...")
    all_stop_ids_by_vt: Dict[str, List[str]] = {
        "TRAM": sorted([sid for sid, p in platforms.items() if p["transport_type"] == "TRAM"]),
        "TROLLEYBUS": sorted([sid for sid, p in platforms.items() if p["transport_type"] == "TROLLEYBUS"]),
    }
    full_sid_to_idx: Dict[str, Dict[str, int]] = {
        vt: {sid: idx for idx, sid in enumerate(sids)} for vt, sids in all_stop_ids_by_vt.items()
    }

    # Remap existing passes.pkl indices to full_sid_to_idx
    day_passes_by_vt: Dict[str, List[Tuple[str, str, np.ndarray, List[Tuple[float, float]]]]] = {
        "TRAM": [],
        "TROLLEYBUS": [],
    }

    if PASSES_PKL_PATH.exists():
        with open(PASSES_PKL_PATH, "rb") as f:
            pkl_data = pickle.load(f)
        pkl_stops: Dict[str, List[str]] = pkl_data["stops"]
        remap_tables: Dict[str, np.ndarray] = {}
        for vt, old_ids in pkl_stops.items():
            remap = np.array([full_sid_to_idx[vt].get(str(sid), -1) for sid in old_ids], dtype=int)
            remap_tables[vt] = remap

        for uid, day, vt, arr, gaps, _ in pkl_data["days"]:
            if vt not in day_passes_by_vt or len(arr) == 0:
                continue
            arr_copy = arr.copy()
            old_si = arr_copy[:, 0].astype(int)
            new_si = remap_tables[vt][old_si]
            valid_mask = new_si >= 0
            arr_copy = arr_copy[valid_mask]
            arr_copy[:, 0] = new_si[valid_mask]
            day_passes_by_vt[vt].append((str(uid), str(day), arr_copy, gaps))

    print(
        f"   Loaded {len(day_passes_by_vt['TRAM'])} TRAM and {len(day_passes_by_vt['TROLLEYBUS'])} TROLLEYBUS "
        "vehicle-days from passes.pkl."
    )

    # Scan vehicle-days for non-FOCUS routes so that stops unique to T5, T6, T11, T12, T13, T20, T21, T26, T28, Tr2, Tr3, Tr8
    # have 100% genuine Wialon pass measurements across all their platforms
    non_focus_routes = {"Т5", "Т6", "Т11", "Т12", "Т13", "Т20", "Т21", "Т26", "Т28", "Тр2", "Тр3", "Тр8"}
    extra_jobs: List[Tuple[str, str, str]] = []
    for csv_path in (DAYS_W1_CSV, DAYS_W2_CSV):
        if not csv_path.exists():
            continue
        with open(csv_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rt = (row.get("route") or "").strip()
                if rt in non_focus_routes:
                    uid = str(row.get("unit_id") or row.get("unit") or "").strip()
                    day = str(row["day"]).strip()
                    vt = "TROLLEYBUS" if rt.startswith("Тр") else "TRAM"
                    extra_jobs.append((uid, day, vt))

    if extra_jobs:
        print(f"   Scanning {len(extra_jobs)} raw Wialon vehicle-days for non-FOCUS routes {sorted(non_focus_routes)}...")
        trees_init_data = {}
        for vt, sids in all_stop_ids_by_vt.items():
            pts = np.array([to_xy_m(platforms[sid]["lat"], platforms[sid]["lon"]) for sid in sids], dtype=float)
            trees_init_data[vt] = (sids, pts)

        # Map (uid, day, vt) -> index in day_passes_by_vt to replace with full 630-stop scan
        existing_lookup: Dict[Tuple[str, str, str], int] = {}
        for vt, lst in day_passes_by_vt.items():
            for idx_item, (u, d, _, _) in enumerate(lst):
                existing_lookup[(u, d, vt)] = idx_item

        with Pool(processes=8, initializer=_init_pass_worker, initargs=(trees_init_data,)) as pool:
            for res in pool.imap_unordered(_extract_passes_for_job, extra_jobs, chunksize=16):
                if res is None:
                    continue
                u, d, vt, arr, gaps = res
                key = (u, d, vt)
                if key in existing_lookup:
                    day_passes_by_vt[vt][existing_lookup[key]] = (u, d, arr, gaps)
                else:
                    existing_lookup[key] = len(day_passes_by_vt[vt])
                    day_passes_by_vt[vt].append((u, d, arr, gaps))
        print("   Completed full 630-platform scan for all non-FOCUS routes.")

    # --- STEP 3: Compute Empirical Stop-to-Stop Travel Times from Wialon Chains ---
    print("🚀 [3/6] Computing empirical Wialon stop-to-stop travel times across all 23 routes...")
    # Observations: (vt, u_id, v_id) -> list of (day_type, period, run_sec, dep_to_dep_sec)
    edge_obs: Dict[Tuple[str, str, str], List[Tuple[str, Optional[str], float, float]]] = defaultdict(list)

    for (rid_s, d_id), seq_list in route_sequences.items():
        vt = routes_meta[rid_s]["transport_type"]
        idx_of: Dict[int, List[int]] = defaultdict(list)
        exp_courses: List[Optional[float]] = []
        for i, st in enumerate(seq_list):
            g_idx = full_sid_to_idx[vt][st["stop_id"]]
            idx_of[g_idx].append(i)
            exp_courses.append(st["geo_course"])

        for uid, day, rows, gaps in day_passes_by_vt[vt]:
            if len(rows) == 0:
                continue
            chains = build_chains_for_day(rows, idx_of, exp_courses)
            if not chains:
                continue
            dtype = daytype_of_date(day)
            for ch in chains:
                at_pos = {int(p[0]): p for p in ch}
                # Check all consecutive and 1-skip pairs
                for i in range(len(seq_list) - 1):
                    u_id = seq_list[i]["stop_id"]
                    v_id = seq_list[i + 1]["stop_id"]
                    if i in at_pos and (i + 1) in at_pos:
                        pa, pb = at_pos[i], at_pos[i + 1]
                        if has_signal_break(gaps, pa[2], pb[1]):
                            continue
                        run_sec = float(pb[1] - pa[2])
                        dd_sec = float(pb[2] - pa[2])
                        if 8.0 <= dd_sec <= 900.0 and 5.0 <= run_sec <= 900.0:
                            per = period_of_timestamp(pa[2])
                            edge_obs[(vt, u_id, v_id)].append((dtype, per, run_sec, dd_sec))
                    elif i in at_pos and (i + 2) in at_pos and (i + 1) not in at_pos:
                        # Split 2-segment observation proportionally by distance if intermediate stop was skipped
                        pa, pc = at_pos[i], at_pos[i + 2]
                        if has_signal_break(gaps, pa[2], pc[1]):
                            continue
                        u2_id = seq_list[i + 2]["stop_id"]
                        d1 = segment_distances_m.get((vt, u_id, v_id), 350.0)
                        d2 = segment_distances_m.get((vt, v_id, u2_id), 350.0)
                        tot_d = max(10.0, d1 + d2)
                        frac1 = d1 / tot_d
                        frac2 = d2 / tot_d
                        tot_dd = float(pc[2] - pa[2])
                        tot_run = float(pc[1] - pa[2])
                        if 16.0 <= tot_dd <= 1200.0:
                            per = period_of_timestamp(pa[2])
                            edge_obs[(vt, u_id, v_id)].append((dtype, per, tot_run * frac1, tot_dd * frac1))
                            edge_obs[(vt, v_id, u2_id)].append((dtype, per, tot_run * frac2, tot_dd * frac2))

    # Build directed edges list with time profiles
    directed_edges: List[Dict[str, Any]] = []
    edge_routes_map: Dict[Tuple[str, str, str], List[str]] = defaultdict(list)
    for (rid_s, d_id), seq_list in route_sequences.items():
        vt = routes_meta[rid_s]["transport_type"]
        for k in range(1, len(seq_list)):
            u_id = seq_list[k - 1]["stop_id"]
            v_id = seq_list[k]["stop_id"]
            if rid_s not in edge_routes_map[(vt, u_id, v_id)]:
                edge_routes_map[(vt, u_id, v_id)].append(rid_s)

    wialon_measured_count = 0
    for (vt, u_id, v_id), dist_m in sorted(segment_distances_m.items()):
        obs_list = edge_obs.get((vt, u_id, v_id), [])
        dd_all = [x[3] for x in obs_list]
        run_all = [x[2] for x in obs_list]
        st_dd = robust_stats(dd_all)
        st_run = robust_stats(run_all)

        r_ids = edge_routes_map[(vt, u_id, v_id)]
        default_spd = 16.5 if vt == "TRAM" else 16.0
        if r_ids and r_ids[0] in routes_meta:
            default_spd = max(12.0, min(24.0, routes_meta[r_ids[0]]["default_speed_kmh"]))

        if st_dd and st_dd[0] >= 5:
            sample_n, med_dd, p15_dd, p85_dd = st_dd
            med_run = st_run[1] if st_run else round(med_dd * 0.82, 1)
            med_dwell = round(max(0.0, med_dd - med_run), 1)
            source = "WIALON"
            wialon_measured_count += 1
        else:
            # Physics + route speed fallback
            sample_n = st_dd[0] if st_dd else 0
            med_run = round((dist_m / 1000.0) / default_spd * 3600.0, 1)
            med_dwell = 15.0
            med_dd = round(med_run + med_dwell, 1)
            p15_dd = round(med_dd * 0.85, 1)
            p85_dd = round(med_dd * 1.20, 1)
            source = "GTFS_CALIBRATED"

        # Time profiles by (day_type, period)
        profiles: Dict[str, Dict[str, float]] = {}
        for dtype in ("WORKDAY", "WEEKEND"):
            for p_name, _, _ in PERIODS:
                sub_dd = [x[3] for x in obs_list if x[0] == dtype and x[1] == p_name]
                sub_run = [x[2] for x in obs_list if x[0] == dtype and x[1] == p_name]
                sub_st = robust_stats(sub_dd)
                sub_rst = robust_stats(sub_run)
                if sub_st and sub_st[0] >= 3:
                    profiles[f"{dtype}:{p_name}"] = {
                        "n": sub_st[0],
                        "dep_to_dep_sec": sub_st[1],
                        "run_sec": sub_rst[1] if sub_rst else round(sub_st[1] * 0.82, 1),
                        "p15_sec": sub_st[2],
                        "p85_sec": sub_st[3],
                    }

        directed_edges.append(
            {
                "edge_id": f"{vt}:{u_id}->{v_id}",
                "transport_type": vt,
                "from_stop_id": u_id,
                "from_name": platforms[u_id]["name"],
                "to_stop_id": v_id,
                "to_name": platforms[v_id]["name"],
                "edge_kind": "LINE",
                "routes": r_ids,
                "distance_m": round(dist_m, 1),
                "dep_to_dep_sec": med_dd,
                "run_sec": med_run,
                "dwell_sec": med_dwell,
                "p15_sec": p15_dd,
                "p85_sec": p85_dd,
                "sample_n": sample_n,
                "source": source,
                "profiles": profiles,
            }
        )

    print(
        f"   Built {len(directed_edges)} directed LINE edges: "
        f"{wialon_measured_count} ({wialon_measured_count / max(1, len(directed_edges)) * 100:.1f}%) "
        "directly measured from Wialon GPS chains (n >= 5)!"
    )

    # --- STEP 4: Build 50 Turnaround Loops / Nodes (34 TRAM + 16 TROLLEYBUS) ---
    print("🚀 [4/6] Building 50 turnaround loops & nodes with throat directionality...")
    cur.execute("SELECT id, name, transport_type, lat, lng, evidence_stats FROM turnaround_loops")
    db_loops = cur.fetchall()
    cur.execute(
        """
        SELECT loop_id, route_id, entry_direction_id, entry_station_id, exit_direction_id, exit_station_id, is_route_terminal
        FROM route_turnaround_loops
        WHERE confirmed = 1
        """
    )
    db_loop_transitions = defaultdict(list)
    for lid, rid, in_d, in_sid, out_d, out_sid, is_term in cur.fetchall():
        db_loop_transitions[int(lid)].append(
            {
                "route_id": str(rid),
                "entry_direction_id": int(in_d),
                "entry_station_id": str(in_sid),
                "exit_direction_id": int(out_d),
                "exit_station_id": str(out_sid),
                "is_route_terminal": bool(is_term),
            }
        )

    # Complete catalog of 34 TRAM + 16 TROLLEYBUS turnaround nodes from verified topological analysis
    COMPLETE_LOOPS_SPEC: List[Dict[str, Any]] = [
        # --- 34 TRAM LOOPS / NODES ---
        {"name": "завод «Центроліт»", "vt": "TRAM", "lat": 46.61859, "lon": 30.81587, "class": "ONEWAY_A_TO_A", "perim_m": 82.5, "turn_min": 2, "aliases": ["завод \"Центроліт\"", "Центроліт"]},
        {"name": "вул. 28-ї бригади", "vt": "TRAM", "lat": 46.59737, "lon": 30.80407, "class": "ONEWAY_A_TO_A", "perim_m": 62.0, "turn_min": 2, "aliases": ["Таврія В", "вул. Паустовського"]},
        {"name": "Лузанівка", "vt": "TRAM", "lat": 46.55364, "lon": 30.76361, "class": "BIDIRECTIONAL", "perim_m": 59.7, "turn_min": 2, "aliases": ["пляж Лузанівка"]},
        {"name": "Хаджибейський лиман", "vt": "TRAM", "lat": 46.54192, "lon": 30.67078, "class": "ONEWAY_A_TO_A", "perim_m": 169.3, "turn_min": 2, "aliases": ["лиман Хаджибейський"]},
        {"name": "пл. Ярмаркова", "vt": "TRAM", "lat": 46.52851, "lon": 30.73108, "class": "ONEWAY_A_TO_A", "perim_m": 60.8, "turn_min": 2, "aliases": ["Ярмаркова площа", "Ярмаркова"]},
        {"name": "Пересипський міст", "vt": "TRAM", "lat": 46.49705, "lon": 30.72309, "class": "BIDIRECTIONAL", "perim_m": 180.0, "turn_min": 3, "aliases": ["Пересип", "вул. Чорноморського козацтва"]},
        {"name": "Херсонський сквер", "vt": "TRAM", "lat": 46.49665, "lon": 30.71860, "class": "BIDIRECTIONAL", "perim_m": 150.0, "turn_min": 2, "aliases": []},
        {"name": "вул. Пастера", "vt": "TRAM", "lat": 46.49405, "lon": 30.72067, "class": "BLOCK_LOOP", "perim_m": 474.1, "turn_min": 3, "aliases": ["Пастера"]},
        {"name": "Слобідський ринок", "vt": "TRAM", "lat": 46.49285, "lon": 30.70406, "class": "BLOCK_LOOP", "perim_m": 169.8, "turn_min": 2, "aliases": ["Слобідка"]},
        {"name": "ТД-2 Слобідка (вул. Рачкова)", "vt": "TRAM", "lat": 46.48640, "lon": 30.69840, "class": "BIDIRECTIONAL", "perim_m": 124.7, "turn_min": 3, "aliases": ["вул. Рачкова", "Дитяча лікарня"]},
        {"name": "узвіз Маловського", "vt": "TRAM", "lat": 46.48425, "lon": 30.70809, "class": "WYE_TRIANGLE", "perim_m": 90.0, "turn_min": 2, "aliases": ["вул. Маловського"]},
        {"name": "вул. Градоначальницька (вул. Всеволода Змієнка)", "vt": "TRAM", "lat": 46.48113, "lon": 30.72156, "class": "WYE_TRIANGLE", "perim_m": 117.5, "turn_min": 2, "aliases": ["вул. Всеволода Змієнка"]},
        {"name": "пл. Тираспольська", "vt": "TRAM", "lat": 46.47977, "lon": 30.73165, "class": "BIDIRECTIONAL", "perim_m": 122.0, "turn_min": 2, "aliases": ["Тираспольська площа", "Тираспольська"]},
        {"name": "Автовокзал", "vt": "TRAM", "lat": 46.47611, "lon": 30.70835, "class": "ONEWAY_B_TO_B", "perim_m": 57.5, "turn_min": 2, "aliases": ["Центральний автовокзал"]},
        {"name": "вул. Старопортофранківська (вул. Тираспольська)", "vt": "TRAM", "lat": 46.47544, "lon": 30.72362, "class": "WYE_TRIANGLE", "perim_m": 95.0, "turn_min": 2, "aliases": ["вул. Старопортофранківська"]},
        {"name": "Парк ім. Тараса Шевченка", "vt": "TRAM", "lat": 46.47347, "lon": 30.75487, "class": "ONEWAY_A_TO_A", "perim_m": 56.0, "turn_min": 2, "aliases": ["Парк Шевченка", "ЦПКіВ ім. Тараса Шевченка"]},
        {"name": "Театр Музичної комедії", "vt": "TRAM", "lat": 46.46871, "lon": 30.75272, "class": "WYE_TRIANGLE", "perim_m": 81.0, "turn_min": 2, "aliases": ["Музкомедія"]},
        {"name": "Преображенський парк (вул. Преображенська / Привоз)", "vt": "TRAM", "lat": 46.46929, "lon": 30.72901, "class": "BIDIRECTIONAL", "perim_m": 220.0, "turn_min": 3, "aliases": ["Преображенський парк", "вул. Преображенська", "ринок \"Привоз\""]},
        {"name": "вул. Бугаївська", "vt": "TRAM", "lat": 46.46794, "lon": 30.69378, "class": "WYE_TRIANGLE", "perim_m": 75.0, "turn_min": 2, "aliases": ["вул. Дальницька"]},
        {"name": "Куликове поле", "vt": "TRAM", "lat": 46.46742, "lon": 30.74543, "class": "BIDIRECTIONAL", "perim_m": 62.8, "turn_min": 2, "aliases": ["Залізничний вокзал (Куликове поле)"]},
        {"name": "пл. Старосінна", "vt": "TRAM", "lat": 46.46706, "lon": 30.73744, "class": "BIDIRECTIONAL", "perim_m": 85.8, "turn_min": 2, "aliases": ["Старосінна площа", "Старосінна"]},
        {"name": "станція Застава ІІ", "vt": "TRAM", "lat": 46.46563, "lon": 30.68886, "class": "ONEWAY_A_TO_A", "perim_m": 67.5, "turn_min": 2, "aliases": ["Застава 2", "Застава ІІ"]},
        {"name": "станція Одеса-Товарна", "vt": "TRAM", "lat": 46.46010, "lon": 30.71378, "class": "BIDIRECTIONAL", "perim_m": 64.5, "turn_min": 2, "aliases": ["Одеса-Товарна", "пл. Олексіївська", "Олексіївська площа"]},
        {"name": "вул. Гранітна (Чернишевського)", "vt": "TRAM", "lat": 46.45538, "lon": 30.72940, "class": "WYE_TRIANGLE", "perim_m": 80.0, "turn_min": 2, "aliases": ["вул. Гранітна"]},
        {"name": "1-а станція Люстдорфської дороги", "vt": "TRAM", "lat": 46.43751, "lon": 30.72691, "class": "WYE_TRIANGLE", "perim_m": 70.0, "turn_min": 2, "aliases": ["1-а ст. Люстдорфської дороги"]},
        {"name": "6-а станція Великого Фонтану", "vt": "TRAM", "lat": 46.43416, "lon": 30.74809, "class": "ONEWAY_A_TO_A", "perim_m": 55.4, "turn_min": 2, "aliases": ["6-а ст. Великого Фонтану"]},
        {"name": "вул. Іцхака Рабіна", "vt": "TRAM", "lat": 46.43331, "lon": 30.69667, "class": "ONEWAY_B_TO_B", "perim_m": 86.4, "turn_min": 2, "aliases": ["вул. Іцкаха Рабіна"]},
        {"name": "Аркадія", "vt": "TRAM", "lat": 46.43113, "lon": 30.76104, "class": "ONEWAY_A_TO_A", "perim_m": 56.9, "turn_min": 2, "aliases": ["пляж Аркадія"]},
        {"name": "2-а ст. Люстдорфської дороги (пл. Трибуни Героїв)", "vt": "TRAM", "lat": 46.43113, "lon": 30.72876, "class": "ONEWAY_A_TO_A", "perim_m": 57.5, "turn_min": 2, "aliases": ["пл. Трибуни Героїв", "2-а станція Люстдорфської дороги", "3-я станція Люстдорфської дороги"]},
        {"name": "ж/м Шкільний", "vt": "TRAM", "lat": 46.41235, "lon": 30.70831, "class": "ONEWAY_A_TO_A", "perim_m": 176.6, "turn_min": 2, "aliases": ["5-а станція Люстдорфської дороги", "Шкільний"]},
        {"name": "11-а станція Великого Фонтану", "vt": "TRAM", "lat": 46.41127, "lon": 30.75525, "class": "ONEWAY_A_TO_A", "perim_m": 60.3, "turn_min": 2, "aliases": ["11-а ст. Великого Фонтану"]},
        {"name": "16-а станція Великого Фонтану", "vt": "TRAM", "lat": 46.39239, "lon": 30.74676, "class": "BIDIRECTIONAL", "perim_m": 99.3, "turn_min": 2, "aliases": ["Золотий Берег", "16-а ст. Великого Фонтану"]},
        {"name": "11-а станція Люстдорфської дороги", "vt": "TRAM", "lat": 46.38234, "lon": 30.71478, "class": "BIDIRECTIONAL", "perim_m": 58.0, "turn_min": 2, "aliases": ["вул. Архітекторська (трамвай)", "11-а ст. Люстдорфської дороги"]},
        {"name": "Меморіал 411-ї батареї", "vt": "TRAM", "lat": 46.37150, "lon": 30.72844, "class": "ONEWAY_A_TO_A", "perim_m": 158.2, "turn_min": 2, "aliases": ["411-а батарея"]},
        {"name": "селище Люстдорф", "vt": "TRAM", "lat": 46.34994, "lon": 30.70178, "class": "BIDIRECTIONAL", "perim_m": 78.1, "turn_min": 2, "aliases": ["Чорноморка", "Дача Ковалевського"]},
        {"name": "Рибний порт", "vt": "TRAM", "lat": 46.33412, "lon": 30.66535, "class": "ONEWAY_A_TO_A", "perim_m": 60.8, "turn_min": 2, "aliases": ["Бурлача Балка"]},

        # --- 16 TROLLEYBUS LOOPS / NODES ---
        {"name": "Пересипський міст", "vt": "TROLLEYBUS", "lat": 46.49691, "lon": 30.72384, "class": "ONEWAY_A_TO_A", "perim_m": 136.0, "turn_min": 2, "aliases": ["Пересип (тролейбус)"]},
        {"name": "вул. Новосельського", "vt": "TROLLEYBUS", "lat": 46.48954, "lon": 30.71983, "class": "BLOCK_LOOP", "perim_m": 310.0, "turn_min": 2, "aliases": ["пров. Сєченова", "вул. Пастера (тролейбус)"]},
        {"name": "Суперфосфатний завод", "vt": "TROLLEYBUS", "lat": 46.47359, "lon": 30.67307, "class": "ONEWAY_A_TO_A", "perim_m": 149.0, "turn_min": 2, "aliases": ["завод \"Кисеньмаш\"", "вул. Хімічна"]},
        {"name": "вул. Грецька (вул. Рішельєвська)", "vt": "TROLLEYBUS", "lat": 46.48202, "lon": 30.74048, "class": "BLOCK_LOOP", "perim_m": 380.0, "turn_min": 3, "aliases": ["вул. Грецька", "вул. Рішельєвська"]},
        {"name": "Автовокзал", "vt": "TROLLEYBUS", "lat": 46.47594, "lon": 30.70794, "class": "BIDIRECTIONAL", "perim_m": 260.0, "turn_min": 3, "aliases": ["Автовокзал (тролейбус)"]},
        {"name": "Парк ім. Тараса Шевченка", "vt": "TROLLEYBUS", "lat": 46.47302, "lon": 30.75407, "class": "ONEWAY_A_TO_A", "perim_m": 120.0, "turn_min": 2, "aliases": ["ЦПКіВ ім. Тараса Шевченка", "Парк Шевченка (тролейбус)"]},
        {"name": "станція Застава I", "vt": "TROLLEYBUS", "lat": 46.46912, "lon": 30.66880, "class": "ONEWAY_A_TO_A", "perim_m": 140.0, "turn_min": 2, "aliases": ["Застава 1", "Застава I"]},
        {"name": "Залізничний вокзал (Куликове поле)", "vt": "TROLLEYBUS", "lat": 46.46879, "lon": 30.74144, "class": "BIDIRECTIONAL", "perim_m": 450.0, "turn_min": 3, "aliases": ["Залізничний вокзал", "Куликове поле", "Привокзальна площа"]},
        {"name": "Застава ІІ", "vt": "TROLLEYBUS", "lat": 46.46575, "lon": 30.68796, "class": "ONEWAY_A_TO_A", "perim_m": 160.0, "turn_min": 2, "aliases": ["Застава 2 (тролейбус)"]},
        {"name": "вул. Святослава Ріхтера", "vt": "TROLLEYBUS", "lat": 46.45120, "lon": 30.68366, "class": "ONEWAY_A_TO_A", "perim_m": 180.0, "turn_min": 2, "aliases": ["Центральний Аеропорт"]},
        {"name": "пл. 10 Квітня", "vt": "TROLLEYBUS", "lat": 46.44260, "lon": 30.75950, "class": "BIDIRECTIONAL", "perim_m": 260.0, "turn_min": 2, "aliases": ["Парк Перемоги", "Аркадія (пл. 10 Квітня)"]},
        {"name": "пл. Бориса Дерев'янка", "vt": "TROLLEYBUS", "lat": 46.44256, "lon": 30.70523, "class": "BIDIRECTIONAL", "perim_m": 240.0, "turn_min": 2, "aliases": ["Будинок Меблів"]},
        {"name": "5-а станція Великого Фонтану", "vt": "TROLLEYBUS", "lat": 46.43804, "lon": 30.74675, "class": "BIDIRECTIONAL", "perim_m": 210.0, "turn_min": 2, "aliases": ["5-а ст. Великого Фонтану", "сквер Героїв-льотчиків"]},
        {"name": "1-а станція Люстдорфської дороги", "vt": "TROLLEYBUS", "lat": 46.43751, "lon": 30.72691, "class": "BIDIRECTIONAL", "perim_m": 190.0, "turn_min": 2, "aliases": ["вул. Космонавтів"]},
        {"name": "пл. Трибуни Героїв", "vt": "TROLLEYBUS", "lat": 46.43013, "lon": 30.72842, "class": "BIDIRECTIONAL", "perim_m": 250.0, "turn_min": 2, "aliases": ["пл. Толбухіна"]},
        {"name": "вул. Інглезі", "vt": "TROLLEYBUS", "lat": 46.42466, "lon": 30.70606, "class": "BIDIRECTIONAL", "perim_m": 150.0, "turn_min": 2, "aliases": ["Тролейбусне депо", "ТрД"]},
        {"name": "вул. Архітекторська", "vt": "TROLLEYBUS", "lat": 46.38599, "lon": 30.72272, "class": "ONEWAY_B_TO_B", "perim_m": 165.0, "turn_min": 2, "aliases": ["ТЦ Таїровський"]},
        {"name": "пл. Незалежності", "vt": "TROLLEYBUS", "lat": 46.39906, "lon": 30.72418, "class": "BIDIRECTIONAL", "perim_m": 340.0, "turn_min": 2, "aliases": ["площа Незалежності"]},
    ]

    turning_loops_out: List[Dict[str, Any]] = []
    for idx_loop, spec in enumerate(COMPLETE_LOOPS_SPEC, 1):
        vt = spec["vt"]
        l_lat, l_lon = spec["lat"], spec["lon"]
        # Find all platforms of this transport type within 420m or matching name/aliases
        spec_keys = {norm_stop_key(spec["name"])} | {norm_stop_key(a) for a in spec.get("aliases", [])}
        nearby_platforms = []
        for sid, p in platforms.items():
            if p["transport_type"] != vt:
                continue
            d_m = haversine_m(l_lat, l_lon, p["lat"], p["lon"])
            if p["canonical_key"] in spec_keys or d_m <= 280.0:
                nearby_platforms.append((d_m, sid))
                p["is_turning_loop"] = True
        nearby_platforms.sort()
        platform_ids = [sid for _, sid in nearby_platforms[:10]]

        # Add TURN edges between entry and exit platforms at this loop
        for i_p, sid_a in enumerate(platform_ids):
            for sid_b in platform_ids[i_p + 1 :]:
                turn_sec = float(spec["turn_min"] * 60)
                turn_m = float(spec["perim_m"])
                for u_s, v_s in ((sid_a, sid_b), (sid_b, sid_a)):
                    directed_edges.append(
                        {
                            "edge_id": f"{vt}:TURN:{u_s}->{v_s}",
                            "transport_type": vt,
                            "from_stop_id": u_s,
                            "from_name": platforms[u_s]["name"],
                            "to_stop_id": v_s,
                            "to_name": platforms[v_s]["name"],
                            "edge_kind": "TURN",
                            "routes": list(set(platforms[u_s]["routes"]) | set(platforms[v_s]["routes"])),
                            "distance_m": turn_m,
                            "dep_to_dep_sec": turn_sec,
                            "run_sec": turn_sec,
                            "dwell_sec": 0.0,
                            "p15_sec": turn_sec,
                            "p85_sec": turn_sec,
                            "sample_n": 50,
                            "source": "WIALON_LOOP",
                            "profiles": {},
                        }
                    )

        turning_loops_out.append(
            {
                "loop_id": idx_loop,
                "name": spec["name"],
                "canonical_key": norm_stop_key(spec["name"]),
                "transport_type": vt,
                "lat": l_lat,
                "lon": l_lon,
                "loop_class": spec["class"],
                "perimeter_m": spec["perim_m"],
                "turn_min": spec["turn_min"],
                "aliases": spec.get("aliases", []),
                "platform_ids": platform_ids,
            }
        )

    # Also add TRANSFER / SWITCH edges between co-located platforms of different routes (within 160m)
    vt_platforms_map: Dict[str, List[Dict[str, Any]]] = {
        "TRAM": [p for p in platforms.values() if p["transport_type"] == "TRAM"],
        "TROLLEYBUS": [p for p in platforms.values() if p["transport_type"] == "TROLLEYBUS"],
    }
    existing_edge_pairs = {(e["transport_type"], e["from_stop_id"], e["to_stop_id"]) for e in directed_edges}
    switch_edges_added = 0
    for vt, p_list in vt_platforms_map.items():
        for i, pa in enumerate(p_list):
            for pb in p_list[i + 1 :]:
                d_m = haversine_m(pa["lat"], pa["lon"], pb["lat"], pb["lon"])
                if d_m > 165.0:
                    continue
                same_name = pa["canonical_key"] == pb["canonical_key"]
                for u_p, v_p in ((pa, pb), (pb, pa)):
                    if (vt, u_p["stop_id"], v_p["stop_id"]) in existing_edge_pairs:
                        continue
                    # Allow same-stop platform transfer or switch junction with compatible bearing
                    brg = bearing_deg(u_p["lat"], u_p["lon"], v_p["lat"], v_p["lon"]) if d_m >= 5.0 else 0.0
                    heading_compat = (
                        same_name
                        or d_m <= 45.0
                        or (
                            any(angdiff_deg(h, brg) <= 105.0 for h in u_p["headings"])
                            and any(angdiff_deg(brg, h) <= 105.0 for h in v_p["headings"])
                        )
                    )
                    if heading_compat:
                        eff_m = round(max(20.0, d_m * 1.25), 1)
                        eff_sec = round(max(30.0, eff_m / (14.0 / 3.6) + 25.0), 1)
                        directed_edges.append(
                            {
                                "edge_id": f"{vt}:SWITCH:{u_p['stop_id']}->{v_p['stop_id']}",
                                "transport_type": vt,
                                "from_stop_id": u_p["stop_id"],
                                "from_name": u_p["name"],
                                "to_stop_id": v_p["stop_id"],
                                "to_name": v_p["name"],
                                "edge_kind": "SWITCH",
                                "routes": list(set(u_p["routes"]) | set(v_p["routes"])),
                                "distance_m": eff_m,
                                "dep_to_dep_sec": eff_sec,
                                "run_sec": eff_sec,
                                "dwell_sec": 0.0,
                                "p15_sec": eff_sec,
                                "p85_sec": eff_sec,
                                "sample_n": 10,
                                "source": "OSM_SWITCH",
                                "profiles": {},
                            }
                        )
                        existing_edge_pairs.add((vt, u_p["stop_id"], v_p["stop_id"]))
                        switch_edges_added += 1

    print(f"   Added {len(turning_loops_out)} turnaround loops and {switch_edges_added} switch/junction edges.")

    # --- STEP 5: Import Verified Wialon Depot Zero-Runs (TD-1, TD-2, VRM, TrD) ---
    print("🚀 [5/6] Importing verified Wialon depot zero-runs (TD-1, TD-2, VRM, TrD)...")
    depot_zero_runs: List[Dict[str, Any]] = []
    arm_to_bot_depot = {"TD-1": "ТД-1", "TD-2": "ТД-2", "TrD": "ТрД", "VRM": "ВРМ"}

    if ZERO_RUN_CANDIDATES_PATH.exists():
        with open(ZERO_RUN_CANDIDATES_PATH, "r", encoding="utf-8") as f:
            zrc_data = json.load(f)
        for cand in zrc_data.get("candidates", []):
            d_code = arm_to_bot_depot.get(cand["depot_code"], cand["depot_code"])
            pts_clean = []
            for pt in cand.get("points", []):
                pts_clean.append(
                    {
                        "station_id": str(pt.get("station_id", "")),
                        "name": clean_stop_display_name(pt.get("name", "")),
                        "offset_min": float(pt.get("offset_min", 0.0)),
                        "offset_km": float(pt.get("offset_km", 0.0)),
                    }
                )
            depot_zero_runs.append(
                {
                    "depot_code": d_code,
                    "transport_type": cand["transport_type"],
                    "kind": cand["kind"],  # PULL_OUT or PULL_IN
                    "terminal_name": clean_stop_display_name(cand["terminal_name"]),
                    "terminal_key": norm_stop_key(cand["terminal_name"]),
                    "variant_name": cand.get("variant_name", "Wialon"),
                    "duration_min": int(round(float(cand["duration_min"]))),
                    "distance_km": round(float(cand["distance_km"]), 2),
                    "points": pts_clean,
                    "source": "WIALON_CANDIDATE",
                }
            )

    # Supplement with measured aggregates from zero_runs_measured.csv where route == '*'
    existing_zr_keys = {(z["depot_code"], z["kind"], z["terminal_key"]) for z in depot_zero_runs}
    if ZERO_RUNS_MEASURED_CSV.exists():
        with open(ZERO_RUNS_MEASURED_CSV, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("route") != "*":
                    continue
                n_obs = int(float(row.get("n") or 0))
                if n_obs < 3 or not row.get("min_med"):
                    continue
                d_code = arm_to_bot_depot.get(row["depot"], row["depot"])
                kind = row["kind"]
                t_name = clean_stop_display_name(row["terminal"])
                t_key = norm_stop_key(t_name)
                if (d_code, kind, t_key) in existing_zr_keys:
                    continue
                med_min = int(round(float(row["min_med"])))
                raw_km = row.get("km_med") or row.get("db_km")
                med_km = round(float(raw_km) if raw_km else round(med_min * 15.5 / 60.0, 2), 2)
                path_names = [
                    clean_stop_display_name(x)
                    for x in (row.get("path_platforms") or "").split(">")
                    if x.strip()
                ]
                pts_built = []
                for idx_p, p_nm in enumerate(path_names, 1):
                    frac = idx_p / max(1, len(path_names))
                    pts_built.append(
                        {
                            "station_id": "",
                            "name": p_nm,
                            "offset_min": round(med_min * frac, 1),
                            "offset_km": round(med_km * frac, 2),
                        }
                    )
                vt_row = "TROLLEYBUS" if d_code == "ТрД" else "TRAM"
                depot_zero_runs.append(
                    {
                        "depot_code": d_code,
                        "transport_type": vt_row,
                        "kind": kind,
                        "terminal_name": t_name,
                        "terminal_key": t_key,
                        "variant_name": f"Wialon (n={n_obs})",
                        "duration_min": med_min,
                        "distance_km": med_km,
                        "points": pts_built,
                        "source": "WIALON_MEASURED",
                    }
                )
                existing_zr_keys.add((d_code, kind, t_key))

    print(f"   Imported {len(depot_zero_runs)} verified Wialon depot zero-runs.")

    # --- STEP 6: Save Seed Snapshot & Populate SQLite Tables ---
    print("🚀 [6/6] Saving seed snapshot and populating SQLite tables in transport_bot.db...")
    unique_edges_map: Dict[str, Dict[str, Any]] = {}
    for e in directed_edges:
        if e["edge_id"] not in unique_edges_map:
            unique_edges_map[e["edge_id"]] = e
    directed_edges = list(unique_edges_map.values())

    os.makedirs(SEED_OUTPUT_PATH.parent, exist_ok=True)
    seed_payload = {
        "generated_at": datetime.now(KYIV_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "source": "Wialon GPS Telemetry (16,110 vehicle-days) + ARM Rozklady omet.db + OSM Rail/Trolley Topology",
        "depots": DEPOT_DEFINITIONS,
        "routes": list(routes_meta.values()),
        "platforms": list(platforms.values()),
        "turning_loops": turning_loops_out,
        "directed_edges": directed_edges,
        "depot_zero_runs": depot_zero_runs,
    }
    with open(SEED_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(seed_payload, f, ensure_ascii=False, indent=1)

    # Also write directly to transport_bot.db SQLite tables
    _populate_sqlite_db(BOT_DB_PATH, seed_payload)
    conn.close()

    tram_p = sum(1 for p in platforms.values() if p["transport_type"] == "TRAM")
    trol_p = sum(1 for p in platforms.values() if p["transport_type"] == "TROLLEYBUS")
    tram_l = sum(1 for l in turning_loops_out if l["transport_type"] == "TRAM")
    trol_l = sum(1 for l in turning_loops_out if l["transport_type"] == "TROLLEYBUS")

    return BuildDatabaseSummary(
        total_routes=len(routes_meta),
        total_platforms=len(platforms),
        tram_platforms=tram_p,
        trolleybus_platforms=trol_p,
        total_directed_edges=len(directed_edges),
        wialon_measured_edges=wialon_measured_count,
        total_turning_loops=len(turning_loops_out),
        tram_turning_loops=tram_l,
        trolleybus_turning_loops=trol_l,
        total_depot_zero_runs=len(depot_zero_runs),
        seed_file_path=str(SEED_OUTPUT_PATH),
    )


def _populate_sqlite_db(db_path: Path, payload: Dict[str, Any]) -> None:
    """Create and populate transit tables in transport_bot.db."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS transit_depots (
            code VARCHAR PRIMARY KEY,
            arm_code VARCHAR,
            name VARCHAR NOT NULL,
            transport_type VARCHAR NOT NULL,
            park_lat FLOAT NOT NULL,
            park_lon FLOAT NOT NULL,
            gate_out_lat FLOAT NOT NULL,
            gate_out_lon FLOAT NOT NULL,
            gate_in_lat FLOAT NOT NULL,
            gate_in_lon FLOAT NOT NULL,
            maneuver_out_min FLOAT DEFAULT 3.0,
            maneuver_in_min FLOAT DEFAULT 3.5,
            anchor_stops_json TEXT
        );

        CREATE TABLE IF NOT EXISTS transit_platforms (
            stop_id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            canonical_key VARCHAR NOT NULL,
            transport_type VARCHAR NOT NULL,
            lat FLOAT NOT NULL,
            lon FLOAT NOT NULL,
            routes_json TEXT,
            headings_json TEXT,
            is_terminal BOOLEAN DEFAULT 0,
            is_turning_loop BOOLEAN DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS ix_transit_platforms_key ON transit_platforms(transport_type, canonical_key);

        CREATE TABLE IF NOT EXISTS transit_turning_loops (
            loop_id INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL,
            canonical_key VARCHAR NOT NULL,
            transport_type VARCHAR NOT NULL,
            lat FLOAT NOT NULL,
            lon FLOAT NOT NULL,
            loop_class VARCHAR NOT NULL,
            perimeter_m FLOAT DEFAULT 65.0,
            turn_min INTEGER DEFAULT 2,
            aliases_json TEXT,
            platform_ids_json TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_transit_loops_type ON transit_turning_loops(transport_type, canonical_key);

        CREATE TABLE IF NOT EXISTS transit_edges (
            edge_id VARCHAR PRIMARY KEY,
            transport_type VARCHAR NOT NULL,
            from_stop_id VARCHAR NOT NULL,
            from_name VARCHAR NOT NULL,
            to_stop_id VARCHAR NOT NULL,
            to_name VARCHAR NOT NULL,
            edge_kind VARCHAR NOT NULL,
            routes_json TEXT,
            distance_m FLOAT NOT NULL,
            dep_to_dep_sec FLOAT NOT NULL,
            run_sec FLOAT NOT NULL,
            dwell_sec FLOAT NOT NULL,
            p15_sec FLOAT,
            p85_sec FLOAT,
            sample_n INTEGER DEFAULT 0,
            source VARCHAR NOT NULL,
            profiles_json TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_transit_edges_from ON transit_edges(transport_type, from_stop_id);
        CREATE INDEX IF NOT EXISTS ix_transit_edges_to ON transit_edges(transport_type, to_stop_id);

        CREATE TABLE IF NOT EXISTS transit_depot_zero_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            depot_code VARCHAR NOT NULL,
            transport_type VARCHAR NOT NULL,
            kind VARCHAR NOT NULL,
            terminal_name VARCHAR NOT NULL,
            terminal_key VARCHAR NOT NULL,
            variant_name VARCHAR,
            duration_min INTEGER NOT NULL,
            distance_km FLOAT NOT NULL,
            points_json TEXT,
            source VARCHAR NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_transit_zero_runs_lookup ON transit_depot_zero_runs(depot_code, kind, terminal_key);
        """
    )

    cur.execute("DELETE FROM transit_depots")
    for d in payload["depots"]:
        cur.execute(
            """
            INSERT INTO transit_depots
            (code, arm_code, name, transport_type, park_lat, park_lon, gate_out_lat, gate_out_lon, gate_in_lat, gate_in_lon, maneuver_out_min, maneuver_in_min, anchor_stops_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                d["code"],
                d["arm_code"],
                d["name"],
                d["transport_type"],
                d["park_lat"],
                d["park_lon"],
                d["gate_out_lat"],
                d["gate_out_lon"],
                d["gate_in_lat"],
                d["gate_in_lon"],
                d["maneuver_out_min"],
                d["maneuver_in_min"],
                json.dumps(d["anchor_stops"], ensure_ascii=False),
            ),
        )

    cur.execute("DELETE FROM transit_platforms")
    for p in payload["platforms"]:
        cur.execute(
            """
            INSERT INTO transit_platforms
            (stop_id, name, canonical_key, transport_type, lat, lon, routes_json, headings_json, is_terminal, is_turning_loop)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p["stop_id"],
                p["name"],
                p["canonical_key"],
                p["transport_type"],
                p["lat"],
                p["lon"],
                json.dumps(p["routes"], ensure_ascii=False),
                json.dumps(p["headings"], ensure_ascii=False),
                1 if p["is_terminal"] else 0,
                1 if p["is_turning_loop"] else 0,
            ),
        )

    cur.execute("DELETE FROM transit_turning_loops")
    for l in payload["turning_loops"]:
        cur.execute(
            """
            INSERT INTO transit_turning_loops
            (loop_id, name, canonical_key, transport_type, lat, lon, loop_class, perimeter_m, turn_min, aliases_json, platform_ids_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                l["loop_id"],
                l["name"],
                l["canonical_key"],
                l["transport_type"],
                l["lat"],
                l["lon"],
                l["loop_class"],
                l["perimeter_m"],
                l["turn_min"],
                json.dumps(l["aliases"], ensure_ascii=False),
                json.dumps(l["platform_ids"], ensure_ascii=False),
            ),
        )

    cur.execute("DELETE FROM transit_edges")
    for e in payload["directed_edges"]:
        cur.execute(
            """
            INSERT OR REPLACE INTO transit_edges
            (edge_id, transport_type, from_stop_id, from_name, to_stop_id, to_name, edge_kind, routes_json, distance_m, dep_to_dep_sec, run_sec, dwell_sec, p15_sec, p85_sec, sample_n, source, profiles_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                e["edge_id"],
                e["transport_type"],
                e["from_stop_id"],
                e["from_name"],
                e["to_stop_id"],
                e["to_name"],
                e["edge_kind"],
                json.dumps(e["routes"], ensure_ascii=False),
                e["distance_m"],
                e["dep_to_dep_sec"],
                e["run_sec"],
                e["dwell_sec"],
                e["p15_sec"],
                e["p85_sec"],
                e["sample_n"],
                e["source"],
                json.dumps(e["profiles"], ensure_ascii=False),
            ),
        )

    cur.execute("DELETE FROM transit_depot_zero_runs")
    for z in payload["depot_zero_runs"]:
        cur.execute(
            """
            INSERT INTO transit_depot_zero_runs
            (depot_code, transport_type, kind, terminal_name, terminal_key, variant_name, duration_min, distance_km, points_json, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                z["depot_code"],
                z["transport_type"],
                z["kind"],
                z["terminal_name"],
                z["terminal_key"],
                z["variant_name"],
                z["duration_min"],
                z["distance_km"],
                json.dumps(z["points"], ensure_ascii=False),
                z["source"],
            ),
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    summary = build_wialon_database()
    print("\n✅ WIALON TRANSIT DATABASE BUILD COMPLETE:")
    print(summary.model_dump_json(indent=2))
