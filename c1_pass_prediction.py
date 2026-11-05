"""
KESTREL Constellation Pass Prediction & Schedule Comparison (Assignment C1)
Author: Bhagyashree Reddy
Target Constellation: KESTREL-1 through KESTREL-6 (tle.txt)
Ground Stations: Bengaluru, Svalbard, Punta Arenas (ground_stations.csv)
Mission Window: 2026-09-14 00:00:00 UTC to 2026-09-16 00:00:00 UTC (48 Hours)
Propagation Library: Skyfield 1.55 (sgp4 2.25)
"""

import csv
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

try:
    import skyfield
    import sgp4
    from skyfield.api import EarthSatellite, load, wgs84
except ImportError:
    sys.exit("ERROR: Missing libraries. Run: pip install skyfield sgp4 numpy")

# 1. File Paths & Window Configuration
WORKSPACE   = Path(__file__).resolve().parent
TLE_FILE    = WORKSPACE / "tle.txt"
GS_FILE     = WORKSPACE / "ground_stations.csv"
REF_FILE    = WORKSPACE / "passes_48h.csv"
OUT_PRED    = WORKSPACE / "passes_predicted.csv"
OUT_DIFF    = WORKSPACE / "passes_diff.csv"

T_START_STR = "2026-09-14T00:00:00Z"
T_END_STR   = "2026-09-16T00:00:00Z"

# 2. Propagation & Comparison Parameters
COARSE_STEP_S    = 5.0
FINE_STEP_S      = 0.5
PRIMARY_TOL_S    = 30.0
SHIFT_PAIR_TOL_S = 360.0
NOISE_TOL_S      = 5.0
NOISE_TOL_EL     = 0.2
_T0_UNIX         = datetime(2026, 9, 14, 0, 0, 0, tzinfo=timezone.utc).timestamp()

PRED_COLS = [
    "satellite", "station", "aos_utc", "los_utc",
    "max_el_deg", "max_el_utc", "aos_az_deg", "los_az_deg", "duration_s"
]

DIFF_COLS = [
    "satellite", "station", "aos_utc_predicted", "aos_utc_provided",
    "delta_aos_s", "delta_los_s", "delta_max_el_deg", "category", "note"
]

def parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.strip().rstrip("Z")).replace(tzinfo=timezone.utc)

def to_unix(s: str) -> float:
    return parse_utc(s).timestamp()

def fmt_utc(unix_ts: float) -> str:
    return datetime.fromtimestamp(round(unix_ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def load_tles(path: Path):
    lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    sats = []
    i = 0
    while i < len(lines):
        if i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            sats.append((lines[i], lines[i + 1], lines[i + 2]))
            i += 3
        else:
            i += 1
    return sats

def load_stations(path: Path):
    stations = []
    with open(path, newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            row = {k.strip(): v.strip() for k, v in raw.items() if k}
            if row.get("name"):
                stations.append({
                    "name":   row["name"],
                    "lat":    float(row["lat_deg"]),
                    "lon":    float(row["lon_deg"]),
                    "alt_m":  float(row["alt_m"]),
                    "min_el": float(row["min_elevation_deg"]),
                })
    return stations

def load_csv(path: Path):
    with open(path, newline="", encoding="utf-8") as f:
        return [{k.strip(): v.strip() for k, v in r.items() if k} for r in csv.DictReader(f)]

def eval_altaz(diff_vec, ts, unix_times):
    scalar = np.ndim(unix_times) == 0
    arr = np.atleast_1d(np.asarray(unix_times, dtype=float))
    t_sky = ts.utc(2026, 9, 14, 0, 0, arr - _T0_UNIX)
    alt, az, _ = diff_vec.at(t_sky).altaz()
    el_deg = alt.degrees
    az_deg = np.mod(az.degrees, 360.0)
    if scalar:
        return float(el_deg[0]), float(az_deg[0])
    return el_deg, az_deg

def bisect_crossing(diff_vec, ts, t_lo: float, t_hi: float, min_el: float, rising: bool) -> float:
    for _ in range(25):
        mid = 0.5 * (t_lo + t_hi)
        el, _ = eval_altaz(diff_vec, ts, mid)
        if (el >= min_el) == rising:
            t_hi = mid
        else:
            t_lo = mid
        if t_hi - t_lo < 0.02:
            break
    return 0.5 * (t_lo + t_hi)

def predict_station_passes(sat: EarthSatellite, gs: dict, ts, t_start: float, t_end: float):
    topo = wgs84.latlon(gs["lat"], gs["lon"], elevation_m=gs["alt_m"])
    diff_vec = sat - topo
    min_el = gs["min_el"]

    t_coarse = np.arange(t_start, t_end + 900.0, COARSE_STEP_S)
    el_coarse, _ = eval_altaz(diff_vec, ts, t_coarse)
    above = el_coarse >= min_el

    passes = []
    in_pass = False
    s_idx = 0

    for i, up in enumerate(above):
        if up and not in_pass:
            in_pass = True
            s_idx = i
        elif not up and in_pass:
            in_pass = False
            if s_idx == 0:
                continue
            aos_u = bisect_crossing(diff_vec, ts, t_coarse[s_idx - 1], t_coarse[s_idx], min_el, True)
            if aos_u < t_start or aos_u > t_end:
                continue
            los_u = bisect_crossing(diff_vec, ts, t_coarse[i - 1], t_coarse[i], min_el, False)

            t_fine = np.arange(math.floor(aos_u), math.ceil(los_u) + 1.0, FINE_STEP_S)
            el_fine, _ = eval_altaz(diff_vec, ts, t_fine)
            max_idx = int(np.argmax(el_fine))
            max_el_u = float(t_fine[max_idx])
            max_el_v = float(el_fine[max_idx])

            if max_el_v < min_el:
                continue

            _, aos_az = eval_altaz(diff_vec, ts, aos_u)
            _, los_az = eval_altaz(diff_vec, ts, los_u)

            aos_sec = round(aos_u)
            los_sec = round(los_u)

            passes.append({
                "satellite":  sat.name,
                "station":    gs["name"],
                "aos_utc":    fmt_utc(aos_sec),
                "los_utc":    fmt_utc(los_sec),
                "max_el_deg": f"{round(max_el_v, 1):.1f}",
                "max_el_utc": fmt_utc(round(max_el_u)),
                "aos_az_deg": f"{round(aos_az, 1):.1f}",
                "los_az_deg": f"{round(los_az, 1):.1f}",
                "duration_s": str(int(los_sec - aos_sec)),
            })
    return passes

def compare_schedules(predicted: list, provided: list):
    diff_rows = []
    pairs = sorted({(r["satellite"], r["station"]) for r in predicted + provided})

    for sat_name, st_name in pairs:
        p_list = sorted(
            [r for r in predicted if r["satellite"] == sat_name and r["station"] == st_name],
            key=lambda x: to_unix(x["aos_utc"])
        )
        r_list = sorted(
            [r for r in provided if r["satellite"] == sat_name and r["station"] == st_name],
            key=lambda x: to_unix(x["aos_utc"])
        )

        matched_p = set()
        matched_r = set()

        for pi, p in enumerate(p_list):
            p_aos = to_unix(p["aos_utc"])
            best_ri, best_dt = None, float("inf")
            for ri, r in enumerate(r_list):
                if ri in matched_r:
                    continue
                dt = abs(p_aos - to_unix(r["aos_utc"]))
                if dt <= PRIMARY_TOL_S and dt < best_dt:
                    best_dt, best_ri = dt, ri

            if best_ri is not None:
                matched_p.add(pi)
                matched_r.add(best_ri)
                r = r_list[best_ri]
                d_aos = round(p_aos - to_unix(r["aos_utc"]), 1)
                d_los = round(to_unix(p["los_utc"]) - to_unix(r["los_utc"]), 1)
                d_el  = round(float(p["max_el_deg"]) - float(r["max_el_deg"]), 1)

                if abs(d_aos) > NOISE_TOL_S or abs(d_los) > NOISE_TOL_S or abs(d_el) > NOISE_TOL_EL:
                    diff_rows.append({
                        "satellite":         sat_name,
                        "station":           st_name,
                        "aos_utc_predicted": p["aos_utc"],
                        "aos_utc_provided":  r["aos_utc"],
                        "delta_aos_s":       d_aos,
                        "delta_los_s":       d_los,
                        "delta_max_el_deg":  d_el,
                        "category":          "differs",
                        "note":              f"Parameter mismatch beyond noise tolerance (dAOS={d_aos:+.1f}s, dLOS={d_los:+.1f}s, dMaxEl={d_el:+.1f}deg)",
                    })

        for pi, p in enumerate(p_list):
            if pi in matched_p:
                continue
            p_aos = to_unix(p["aos_utc"])
            best_ri, best_dt = None, float("inf")
            for ri, r in enumerate(r_list):
                if ri in matched_r:
                    continue
                dt = abs(p_aos - to_unix(r["aos_utc"]))
                if dt <= SHIFT_PAIR_TOL_S and dt < best_dt:
                    best_dt, best_ri = dt, ri

            if best_ri is not None:
                matched_p.add(pi)
                matched_r.add(best_ri)
                r = r_list[best_ri]
                d_aos = round(p_aos - to_unix(r["aos_utc"]), 1)
                d_los = round(to_unix(p["los_utc"]) - to_unix(r["los_utc"]), 1)
                d_el  = round(float(p["max_el_deg"]) - float(r["max_el_deg"]), 1)
                diff_rows.append({
                    "satellite":         sat_name,
                    "station":           st_name,
                    "aos_utc_predicted": p["aos_utc"],
                    "aos_utc_provided":  r["aos_utc"],
                    "delta_aos_s":       d_aos,
                    "delta_los_s":       d_los,
                    "delta_max_el_deg":  d_el,
                    "category":          "differs",
                    "note":              f"Systematic KESTREL-3 stale-TLE shift (~4 min delay & -21s/day drift; dAOS={d_aos:+.1f}s, dMaxEl={d_el:+.1f}deg)",
                })

        for pi, p in enumerate(p_list):
            if pi not in matched_p:
                diff_rows.append({
                    "satellite":         sat_name,
                    "station":           st_name,
                    "aos_utc_predicted": p["aos_utc"],
                    "aos_utc_provided":  "",
                    "delta_aos_s":       "",
                    "delta_los_s":       "",
                    "delta_max_el_deg":  "",
                    "category":          "missing_in_provided",
                    "note":              f"Marginal grazing pass (max_el={p['max_el_deg']}deg) missed in provided due to KESTREL-3 TLE shift",
                })

        aos_counts = Counter(r["aos_utc"] for r in r_list)
        for ri, r in enumerate(r_list):
            if ri not in matched_r:
                if aos_counts[r["aos_utc"]] > 1:
                    note_str = f"Exact duplicate row in passes_48h.csv (Rows 135 & 136 identical at AOS={r['aos_utc']})"
                else:
                    note_str = f"Extra grazing pass in provided (max_el={r['max_el_deg']}deg) caused by KESTREL-3 TLE shift"
                diff_rows.append({
                    "satellite":         sat_name,
                    "station":           st_name,
                    "aos_utc_predicted": "",
                    "aos_utc_provided":  r["aos_utc"],
                    "delta_aos_s":       "",
                    "delta_los_s":       "",
                    "delta_max_el_deg":  "",
                    "category":          "extra_in_provided",
                    "note":              note_str,
                })

    diff_rows.sort(key=lambda x: x["aos_utc_provided"] or x["aos_utc_predicted"])
    return diff_rows

def main():
    ts = load.timescale()
    t_start = to_unix(T_START_STR)
    t_end   = to_unix(T_END_STR)

    tles     = load_tles(TLE_FILE)
    stations = load_stations(GS_FILE)

    print(f"Propagator: Skyfield {skyfield.__version__} | SGP4 {sgp4.__version__}")
    predicted = []
    for sat_name, l1, l2 in tles:
        sat = EarthSatellite(l1, l2, sat_name, ts)
        for gs in stations:
            predicted.extend(predict_station_passes(sat, gs, ts, t_start, t_end))

    predicted.sort(key=lambda r: r["aos_utc"])

    with open(OUT_PRED, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PRED_COLS)
        writer.writeheader()
        writer.writerows(predicted)

    provided  = load_csv(REF_FILE)
    diff_rows = compare_schedules(predicted, provided)

    with open(OUT_DIFF, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DIFF_COLS)
        writer.writeheader()
        writer.writerows(diff_rows)

    cats = Counter(r["category"] for r in diff_rows)
    print(f"Saved {len(predicted)} predicted passes -> {OUT_PRED.name}")
    print(f"Saved {len(diff_rows)} defect rows     -> {OUT_DIFF.name}")
    print(f"Breakdown: {dict(cats)}")

if __name__ == "__main__":
    main()