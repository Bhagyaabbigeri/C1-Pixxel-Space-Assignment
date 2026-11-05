### 1. Method & Inferred Conventions
To predict passes of `KESTREL-1`–`KESTREL-6` (`tle.txt`) over `Bengaluru`, `Svalbard`, and `Punta Arenas` (`ground_stations.csv`) across `2026-09-14T00:00:00Z`–`2026-09-16T00:00:00Z`, `c1_pass_prediction.py` uses **Skyfield 1.55 (`sgp4` 2.25)** in the WGS84 frame. It scans a `5 s` grid above `min_elevation_deg` (`5.0°`), refines AOS/LOS via bisection (`<0.02 s`), and evaluates a `0.5 s` grid for peak elevation (`max_el_deg`, `max_el_utc`).

Inferred `passes_48h.csv` conventions:
- **Schema & Sorting:** `satellite,station,aos_utc,los_utc,max_el_deg,max_el_utc,aos_az_deg,los_az_deg,duration_s`, sorted ascending by `aos_utc`.
- **Time & Duration:** UTC ISO-8601 rounded to integer seconds (`YYYY-MM-DDTHH:MM:SSZ`); `duration_s=los_utc-aos_utc`.
- **Angles & Azimuth:** Rounded to `0.1°`, referenced to True North (`0.0°–360.0°` clockwise, East=`90.0°`).
- **Refraction:** Disabled (`0.0°` refraction; geometric `5.0°` mask).
- **Window Boundaries:** Passes starting in `[2026-09-14T00:00:00Z, 2026-09-16T00:00:00Z]` are **not truncated** at window end—proven by Row 264 (`KESTREL-3`, Svalbard, `aos_utc=2026-09-15T23:54:58Z`, `los_utc=2026-09-16T00:00:46Z`, `duration_s=348`).

### 2. Matching Rule & Tolerance
- **Two-Stage Matching:** Stage 1 pairs passes 1-to-1 on `(satellite, station)` within **`±30 s`** on `aos_utc`, filtering tool noise (`|ΔAOS|≤5.0 s`, `|ΔLOS|≤5.0 s`, `|Δmax_el|≤0.2°`) and flagging larger deviations as `differs`. Stage 2 pairs remaining passes within `±360 s` to quantify systematic TLE shifts before classifying unmatched rows as `missing_in_provided` or `extra_in_provided`.
- **Why `±30 s` (`5 s` noise floor):** LEO passes (~535 km) last `50–585 s` every `~95 min`. SGP4 variations (WGS72/WGS84 constants, UT1−UTC, grid rounding) shift `5.0°` crossings by `0–2 s`, whereas real defects shift passes by `10–300 s`.

### 3. Explanation of Every Difference & Operational Trust
Across `KESTREL-1, 2, 4, 5 (unique), and 6` (222 passes), predictions match `passes_48h.csv` within `0–1 s` and `0.0–0.1°`. All 43 `passes_diff.csv` rows trace to two defects:
1. **Exact Duplicate Row (`extra_in_provided`, 1 row):** Rows 135–136 (`KESTREL-5`, `Svalbard`, `2026-09-15T00:40:25Z`–`00:45:00Z`, `max_el_deg=7.9°`, `duration_s=275`) are 100% identical across nine columns (export bug).
2. **Stale/Corrupted `KESTREL-3` TLE (`differs`: 39, `missing_in_provided`: 1, `extra_in_provided`: 2):** Every `KESTREL-3` pass in `passes_48h.csv` arrives **`226–278 s` (~3.8–4.6 min) late**. Linear regression of `ΔAOS` vs. time from `KESTREL-3`'s epoch (`2026-09-13T01:30:00Z`) proves a **`-208.9 s`** offset (`ΔMA≈-13.25°`) plus **`-21.02 s/day`** drift (`Δn≈-0.00367 rev/day`) from a stale TLE:
   * **39 matched passes (`differs`):** Shifted `-226 s` to `-278 s`, rotating Earth `~1°` longitude and altering `max_el_deg` up to `13.3°` (Bengaluru `2026-09-15T17:10:30Z`: `82.2°` vs. `68.9°`).
   * **1 missed grazing pass (`missing_in_provided`):** `Svalbard` (`2026-09-15T01:42:31Z`, `5.1°`) drops below `5.0°`.
   * **2 extra grazing passes (`extra_in_provided`):** `Svalbard` (`2026-09-14T05:12:55Z`, `5.1°`) and `Bengaluru` (`2026-09-14T15:58:06Z`, `5.2°`) exceed `5.0°` only under the corrupted TLE.
- **Operational Trust:** Trust **`passes_predicted.csv`**. `passes_48h.csv` double-books Svalbard (`KESTREL-5`, `00:40:25Z`) and points antennas ~4 minutes late (`~1,800 km` error) on `KESTREL-3`, losing contacts.

### 4. Process Changes to Prevent Recurrence
1. **TLE Checksum Gate:** Embed `tle.txt` SHA-256 hashes and NORAD checksums in headers; block release if any TLE diverges from the flight dynamics store.
2. **Pre-Publish Uniqueness Gate:** Enforce CI checks for `(satellite, station, aos_utc)` uniqueness, `>50 min` separation, `duration_s==los_utc-aos_utc`, and `max_el_deg>=min_elevation_deg`.
3. **Shadow-Propagator Cross-Check:** Diff schedules against a secondary propagator and quarantine passes (`|ΔAOS|>10s`).

## Decision record
- **Approach chosen and why:** Used Skyfield/SGP4 with `5 s` coarse bracketing and sub-second bisection, paired with a two-stage comparator (`±30 s` primary window with a `5 s` noise floor, plus a `±360 s` diagnostic window). This separates `0–1 s` rounding noise on `KESTREL-1, 2, 4, 5, 6` from the exact `KESTREL-5` duplicate and `KESTREL-3`'s `-208.9 s` offset / `-21.02 s/day` drift.
- **Alternatives considered and why rejected:** Rejected flagging `|ΔAOS| > 1 s` as `differs` because `1 s` integer-rounding jitter is normal tool noise, not a defect. Rejected leaving `KESTREL-3`'s 39 shifted passes as unpaired `missing`/`extra` rows because pairing them quantifies the exact `-21.02 s/day` mean-motion drift that proves a wrong TLE was used.
- **What breaks at scale (10x satellites, 10x data, a new operator):** At 60 satellites and 30 stations, fine time-stepping across all pairs becomes slow; production pipelines should use vectorized `30 s` coarse screening with analytical root-finding and parallel worker pools. For a new operator, manual CSV inspection fails—automated conflict, duplicate, and TLE-epoch gates are mandatory.
- **AI assistance:**
  * **What you asked:** Asked AI to scaffold the Skyfield pass-prediction script, CSV comparator, and regression analysis on the `KESTREL-3` timing residuals.
  * **What you kept:** Kept the bisection horizon-crossing logic, CSV schema formatting, and two-stage matching structure.
  * **What you changed:** Replaced the initial slow `eval_altaz` function that built Python datetime lists (taking 20+ seconds) with a highly optimized vectorised time converter (`ts.utc(2026, 9, 14, 0, 0, arr - _T0_UNIX)`), reducing script execution time from over 20 seconds down to **under 1 second**. Also replaced the `1 s` diff trigger with a `5 s` / `0.2°` noise floor and added secondary diagnostic pairing for `KESTREL-3`'s shifted passes.
  * **Where it was wrong:** An earlier AI run flagged 82 normal passes as `differs` due to `1 s` rounding differences and dumped 40 `missing` + 41 `extra` rows for `KESTREL-3` without realizing they were the same passes shifted by ~4 minutes from a wrong `KESTREL-3` TLE.