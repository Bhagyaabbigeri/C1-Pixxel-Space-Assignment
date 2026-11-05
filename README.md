# KESTREL Constellation — Pass Prediction & Schedule Defect Analysis
### Assignment C1 | Pixxel Mission Operations Assessment

**Author:** Bhagyashree Reddy  
**Engine:** Skyfield 1.55 · sgp4 2.25 · WGS84 Topocentric  
**Window:** `2026-09-14T00:00:00Z` → `2026-09-16T00:00:00Z` (48 h)

---

## Repository Structure

```
C1-Pixxel-Space-Assignment/
├── tle.txt                  # TLE sets for KESTREL-1 through KESTREL-6
├── ground_stations.csv      # Geodetic coordinates + 5° elevation masks
├── passes_48h.csv           # Provided baseline schedule (264 rows, with defects)
├── c1_pass_prediction.py    # Standalone prediction + comparison script
├── passes_predicted.csv     # OUTPUT — predicted schedule (262 rows, ~27 KB)
├── passes_diff.csv          # OUTPUT — discrepancy report (43 rows, ~8 KB)
└── README.md
```

---

## Input Data

### Ground Stations

| Station | Code | Lat (°N) | Lon (°E) | Alt (m) | Min Elev |
|---|---|:---:|:---:|:---:|:---:|
| Bengaluru | BLR | +12.97 | +77.59 | 920 | 5.0° |
| Svalbard | SVA | +78.23 | +15.39 | 450 | 5.0° |
| Punta Arenas | PTA | −53.16 | −70.91 | 30 | 5.0° |

### TLE Constellation

Six co-planar SSO satellites — 97.48° inclination, ~15.15 rev/day (~520 km altitude). KESTREL-1–4 are from launch 2026-045; KESTREL-5–6 from 2026-071.

---

## Algorithm

Pass finding uses a **coarse → bisect → fine** approach per (satellite, station) pair:

1. **Coarse scan** — 5 s steps across the 48 h window; detect elevation sign changes above 5°
2. **Bisection** — 25-iteration binary search on each AOS/LOS crossing → <0.02 s precision
3. **Fine scan** — 0.5 s resolution between AOS/LOS to find peak elevation epoch and azimuths
4. **Round** all timestamps to 1 s, angles to 0.1° — matching the reference convention

Comparison uses a **two-pass greedy matcher** per (satellite, station) group:
- Pass 1 (±30 s) — catches noise-level mismatches → `differs`
- Pass 2 (±360 s) — catches the systematic KESTREL-3 ~240 s drift → `differs`
- Remaining unmatched → `missing_in_provided` or `extra_in_provided`

---

## Pass Count Summary — `passes_predicted.csv` (262 total)

| Satellite | BLR | SVA | PTA | Total |
|---|:---:|:---:|:---:|:---:|
| KESTREL-1 | 7 | 26 | 11 | **44** |
| KESTREL-2 | 8 | 26 | 12 | **46** |
| KESTREL-3 | 4 | 26 | 10 | **40** |
| KESTREL-4 | 7 | 26 | 12 | **45** |
| KESTREL-5 | 7 | 26 | 10 | **43** |
| KESTREL-6 | 5 | 27 | 12 | **44** |
| **Total** | **38** | **157** | **67** | **262** |

> Svalbard (78°N) captures ~60% of all passes — it lies near the orbit pole of this 97.48°-inclined SSO constellation, so every revolution crosses within range.

---

## Inferred Conventions from `passes_48h.csv`

| Convention | Rule |
|---|---|
| Time format | ISO-8601 UTC, integer seconds: `YYYY-MM-DDTHH:MM:SSZ` |
| Duration | `duration_s = round(los) − round(aos)` as integer |
| Angles | Rounded to `0.1°`; True North clockwise; **no atmospheric refraction** |
| Elevation mask | Geometric `5.0°` only |
| Window boundary | Filter on `aos_utc`; passes that start before `T_END` run to natural LOS |

---

## Defect Analysis — `passes_diff.csv` (43 rows)

| Category | Satellite | Count | Root Cause |
|---|---|:---:|---|
| `differs` | KESTREL-3 | **39** | Stale TLE — all 39 passes delayed 226–278 s with −21 s/day linear drift (ΔMA ≈ −13.25°) |
| `extra_in_provided` | KESTREL-3 | **2** | Ghost grazing passes (5.1°, 5.2°) that appear only under the shifted TLE |
| `missing_in_provided` | KESTREL-3 | **1** | Grazing pass (5.1° max el) drops below mask under shifted TLE, so absent from reference |
| `extra_in_provided` | KESTREL-5 | **1** | Exact duplicate row — Rows 135 & 136 of `passes_48h.csv` are 100% identical |
| **Clean matches** | KESTREL-1,2,4,5,6 | **222** | All within ≤1 s / ≤0.1° — no defects |

> **KESTREL-1, 2, 4, 5, 6** are defect-free. Only **KESTREL-3** (stale TLE) and one KESTREL-5 duplicate row are problematic.

---

## Installation & Execution

```bash
pip install skyfield sgp4 numpy
python c1_pass_prediction.py
```

**Expected output:**
```
Propagator: Skyfield 1.55 | SGP4 2.25
Saved 262 predicted passes -> passes_predicted.csv
Saved 43 defect rows       -> passes_diff.csv
Breakdown: {'differs': 39, 'extra_in_provided': 3, 'missing_in_provided': 1}
```

No arguments or configuration needed — the script resolves all paths relative to its own directory. Runtime: ~5–15 s on a modern laptop.

---

## CSV Schema

### `passes_predicted.csv`

| Column | Unit | Description |
|---|---|---|
| `satellite` | — | `KESTREL-1` … `KESTREL-6` |
| `station` | — | `Bengaluru` / `Svalbard` / `Punta Arenas` |
| `aos_utc` | UTC (1 s) | Acquisition of Signal |
| `los_utc` | UTC (1 s) | Loss of Signal |
| `max_el_deg` | ° (0.1°) | Peak elevation |
| `max_el_utc` | UTC (1 s) | Epoch of peak elevation |
| `aos_az_deg` | ° (0.1°) | Azimuth at AOS (True North CW) |
| `los_az_deg` | ° (0.1°) | Azimuth at LOS (True North CW) |
| `duration_s` | s (int) | `round(los) − round(aos)` |

### `passes_diff.csv`

| Column | Description |
|---|---|
| `satellite`, `station` | Identifies the pass |
| `aos_utc_predicted` / `aos_utc_provided` | AOS from each source (blank if absent) |
| `delta_aos_s`, `delta_los_s` | `predicted − provided` in seconds |
| `delta_max_el_deg` | `predicted − provided` in degrees |
| `category` | `differs` / `missing_in_provided` / `extra_in_provided` |
| `note` | Root cause with quantitative evidence |

---

*Bhagyashree Reddy · Pixxel Mission Operations · Assignment C1*
