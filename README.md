# Delivery Route Planning — Synthetic Data Generator
YottaFlex.ai Round 2 · Associate AI Forward Deployed Engineer · 72-hour code challenge

Deterministic generator for an end-to-end delivery planning workflow: vehicles, stops, time windows, capacities,
driver shifts, routes, simulated outcomes, and **labelled anomalies with a separate ground truth**. Pure Python 3.9+ standard library (pytest only for tests).

## Run it
```bash
python generator.py --scale full    --seed 20261022 --out data/full      # 500 sites, 2,000 deliveries, 100 vehicles, 30 days
python generator.py --scale starter --seed 20261022 --out data/starter   # 50 sites, 200 deliveries, 12 vehicles, 5 days
python validate.py data/full/csv --ground-truth data/full/ground_truth/ground_truth.csv
python repro_check.py --scale full --report data/full/docs/reproducibility_report.json
python -m pytest -q          # or: make all
```
Same generator for every scale; override any size with `--sites --deliveries --vehicles --days --anomalies`.

## Outputs (per dataset directory)
| path | content |
|---|---|
| `csv/`, `json/` | 13 tables (JSON skips the 120k-row matrix) — the **input** dataset incl. injected anomalies |
| `sql/schema.sql`, `sql/seed.sql` | DDL with PK/FK + INSERT seed (loads cleanly in SQLite; `PRAGMA foreign_key_check` = 0 rows) |
| `baseline_csv/` | the 6 tables as they were *before* injection (clean baseline) |
| `ground_truth/ground_truth.csv/.json` | injected anomalies (issue_type, entity, original/injected value, detection rule) |
| `ground_truth/ground_truth_labels.csv` | expected decision / outcome / reason per delivery |
| `docs/` | `data_dictionary.md/.csv`, `source_manifest.json`, `validation_summary.json`, `dataset_manifest.json` (seed, command, row counts, SHA-256), `reproducibility_report.json` |

Ground truth is never referenced by any input column (tests enforce this).

## Data model (details in `docs/data_dictionary.md`)
`CustomerSite` (+depot SITE-000000) → `Order` 1:1 `Delivery` 1:1 `TimeWindow`; `Vehicle` 1:N `VehicleCapacity` (effective-dated, some refitted mid-period);
`Driver` N:M `Vehicle` via bridge `Shift`; `Shift` 1:0..1 `Route` 1:N `RouteStop` 1:1 `DeliveryOutcome`;
`TravelTimeMatrix` = per-day directed matrix, 4 time bands, traffic scenario per day (NORMAL/RAIN/EVENT_CONGESTION/HOLIDAY_LIGHT);
`StatusEvent` = append-only lifecycle history (Delivery: CREATED→SCHEDULED→DISPATCHED→DELIVERED|FAILED, or CREATED→UNSERVED; Route: PLANNED→DISPATCHED→IN_PROGRESS→COMPLETED).
IDs: `ORD-2026-000001`, `DEL-2026-000001`, `VEH-000001`, `DRV-000001`, `RTE-2026-000001`, `STOP-<route-id>-001` (+ `SITE-`, `SHF-2026-`, `VCAP-`, `TW-`, `OUT-2026-`, `EVT-`).

## How data is generated (parents → children, derived from source records)
1. Sites (clustered synthetic coordinates in a Hyderabad-sized bounding box, access rules, opening hours) → fleet (4 classes, capacity versions, maintenance) → drivers (LMV/HMV) → orders/deliveries (log-normal demand + 5 % bulk, priority, service time, HARD/SOFT windows inside site hours).
2. Per day: traffic scenario, matrix (haversine × seeded circuity, 32 km/h, band multipliers 1.0/1.45/1.10/1.60), shifts (driver+vehicle, qualified licence), then a **constraint-checking insertion planner** (capacity kg/m³, max stops, restricted sites, hard windows, site hours, shift end − 15 min). Deliveries that cannot be placed are explicitly `UNSERVED` with a reason: `NO_FEASIBLE_VEHICLE`, `TIME_WINDOW_INFEASIBLE`, `FLEET_EXHAUSTED`.
3. Route/stop totals, distances, times, load, utilisation, counts and statuses are computed from the plan, never drawn independently.

### Outcome rules
Actual leg = planned leg × log-normal(σ by scenario) (+3 % chance of a 10–35 min incident). Stop outcome, in order:
`SITE_CLOSED` if arrival after closing → `HARD_WINDOW_MISSED` if HARD window and arrival > end + 15 min → `ADDRESS_NOT_FOUND` with p = 0.30 / 0.02 / 0 for LOW / MEDIUM / HIGH geocode quality → `CUSTOMER_ABSENT` with p = 0.015 + 0.002 × delay-vs-plan min (cap 0.20) → else `DELIVERED` (waits if early). If finishing a stop plus the return leg would exceed shift end, that stop and all later ones are `NOT_ATTEMPTED` with `SHIFT_LIMIT_REACHED`. Every failure carries a reason code.

### Injected edge cases (labelled in `ground_truth`, 8 each at full scale, 2 at starter)
`ROUTE_EXCEEDS_CAPACITY` · `STOP_OMITTED` · `STOP_DUPLICATED` · `ARRIVAL_BEFORE_PREV_DEPARTURE` · `DRIVER_SHIFT_EXCEEDED` · `COORDINATE_OUTSIDE_REGION`.
Each touches only its target rows (derived fields of that row/route are kept consistent), on distinct routes; no other rows are altered.

## Validation (`validate.py`)
PK uniqueness, ID formats, required/enum/unique, FK integrity (incl. polymorphic events), date ordering, arithmetic reconciliation (loads, counts, distances, times re-derived from the matrix, delays), matrix reproducibility from coordinates + seed, capacity versions, lifecycle transitions and final-state agreement, restricted vehicles, driver qualification, double-booking, hard windows, duplicates, "assigned or explicitly unserved", failed ⇒ reason code.

Results at full scale (seed 20261022): 2,000 deliveries → 1,915 assigned (604 routes) / 85 unserved; 1,825 delivered / 82 failed;
**baseline: 0 violations**; with injection **48/48 anomalies detected, 0 false positives, 0 collateral findings** (`docs/validation_summary.json`).

## Reproducibility
Fixed seed 20261022; separate seeded streams per stage; hashing via CRC32 (no Python `hash()`), no wall-clock values.
`repro_check.py` regenerates twice and compares row counts and SHA-256 of all 22 CSV/ground-truth files → **identical** (a different seed differs as control). Report: `data/full/docs/reproducibility_report.json`.

## Provenance / lawful use
No external data, scraping, or personal data. Drivers are pseudonyms. Coordinates are synthetic points in a bounding box (`docs/source_manifest.json`).

## Assumptions / limitations
Synthetic Euclidean-based road distances (no road network); one delivery per stop; single depot; no retry deliveries after failure (failure recorded with reason); travel matrix covers only nodes active that day.
