# Data Dictionary

Generated from `schema.py` (single source of truth). Times are local-naive ISO-8601; units as stated. `req` = required. IDs are immutable and zero-padded.


## CustomerSite — `customer_site`

Delivery locations (500 customers + 1 depot, SITE-000000) with synthetic geocoordinates and access rules.

- **Primary key:** site_id
- **Foreign keys:** none
- **Cardinality:** CustomerSite 1:N Order; CustomerSite 1:N Delivery; CustomerSite 1:N RouteStop; CustomerSite(depot) 1:N Vehicle (home depot); CustomerSite N:M CustomerSite via TravelTimeMatrix (per day)

| field | type | req | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| site_id | string | Y | |  | Y | SITE-\d{6}; SITE-000000 is the depot; customers SITE-000001.. |
| site_name | string | Y | |  | N | synthetic label, non-empty |
| site_type | enum | Y | CUSTOMER|DEPOT | | N | |
| site_category | enum | Y | RETAIL|WAREHOUSE|CLINIC|SCHOOL|OFFICE|RESTAURANT|DEPOT | | N | |
| zone | enum | Y | CENTRAL|NORTH|SOUTH|EAST|WEST | | N | derived from offset to depot (<5 km = CENTRAL) |
| latitude | float | Y | | deg | N | inside BBOX 17.20..17.60 |
| longitude | float | Y | | deg | N | inside BBOX 78.25..78.65 |
| geocode_quality | enum | Y | HIGH|MEDIUM|LOW | | N | drives ADDRESS_NOT_FOUND probability |
| max_vehicle_class_rank | int | Y | 1..4 | | N | largest vehicle class rank allowed on site (1=VAN_S..4=TRUCK_H) |
| access_restriction | enum | Y | NONE|NO_TRUCK_H|VANS_ONLY | | N | derived: rank4=NONE, rank3=NO_TRUCK_H, rank2=VANS_ONLY |
| open_time | time | Y | | HH:MM | N | open_time < close_time |
| close_time | time | Y | | HH:MM | N | |
| service_factor | float | Y | | x | N | 0.8..1.6 multiplier on service duration |
| status | enum | Y | ACTIVE|INACTIVE | | N | |
| effective_from | date | Y | |  | N | |
| effective_to | date | N | |  | N | blank = open-ended |

## Order — `order`

Customer demand. One order is fulfilled by exactly one planned Delivery.

- **Primary key:** order_id
- **Foreign keys:** site_id -> customer_site.site_id
- **Cardinality:** CustomerSite 1:N Order; Order 1:1 Delivery

| field | type | req | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| order_id | string | Y | |  | Y | ORD-2026-\d{6};  |
| site_id | string | Y | |  | N | FK customer_site |
| order_date | date | Y | |  | N | < requested_date |
| requested_date | date | Y | |  | N | = delivery.planned_date |
| demand_kg | float | Y | | kg | N | > 0 |
| demand_volume_m3 | float | Y | | m3 | N | > 0; = demand_kg / density(180..450 kg/m3) |
| priority | enum | Y | 1|2|3 | | N | 1=urgent, 2=standard, 3=deferrable |
| order_status | enum | Y | DELIVERED|FAILED|UNSERVED | | N | terminal state; = delivery.delivery_status (history in status_event) |

## Delivery — `delivery`

Planned delivery task for an order; either assigned to a route or explicitly unserved with a reason.

- **Primary key:** delivery_id
- **Foreign keys:** order_id -> order.order_id, site_id -> customer_site.site_id, assigned_route_id -> route.route_id
- **Cardinality:** Order 1:1 Delivery; Delivery 1:1 TimeWindow; Route 1:N Delivery (assigned); Delivery 0..1:1 RouteStop; Delivery 0..1:1 DeliveryOutcome

| field | type | req | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| delivery_id | string | Y | |  | Y | DEL-2026-\d{6};  |
| order_id | string | Y | |  | Y | FK order |
| site_id | string | Y | |  | N | FK customer_site; = order.site_id |
| planned_date | date | Y | |  | N | |
| demand_kg | float | Y | | kg | N | = order.demand_kg |
| demand_volume_m3 | float | Y | | m3 | N | = order.demand_volume_m3 |
| priority | enum | Y | 1|2|3 | | N | = order.priority |
| service_minutes | float | Y | | min | N | clip((6+0.012*kg)*site.service_factor, 5, 60) |
| assignment_status | enum | Y | ASSIGNED|UNSERVED | | N | |
| assigned_route_id | string | N | |  | N | required iff ASSIGNED |
| unserved_reason_code | enum | N | NO_FEASIBLE_VEHICLE|TIME_WINDOW_INFEASIBLE|FLEET_EXHAUSTED | | N | required iff UNSERVED |
| delivery_status | enum | Y | DELIVERED|FAILED|UNSERVED | | N | terminal state of lifecycle |

## Vehicle — `vehicle`

Fleet vehicles (4 classes) based at the depot.

- **Primary key:** vehicle_id
- **Foreign keys:** depot_site_id -> customer_site.site_id
- **Cardinality:** Vehicle 1:N VehicleCapacity (effective-dated); Vehicle N:M Driver via Shift; Vehicle 1:N Route

| field | type | req | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| vehicle_id | string | Y | |  | Y | VEH-\d{6};  |
| registration_no | string | Y | |  | Y | synthetic plate |
| vehicle_class | enum | Y | VAN_S|VAN_L|TRUCK_M|TRUCK_H | | N | |
| class_rank | int | Y | 1..4 | | N | VAN_S=1, VAN_L=2, TRUCK_M=3, TRUCK_H=4 |
| cost_per_km | float | Y | | INR/km | N | |
| fixed_cost_per_day | float | Y | | INR | N | |
| depot_site_id | string | Y | |  | N | FK customer_site (DEPOT) |
| status | enum | Y | ACTIVE|MAINTENANCE | | N | MAINTENANCE vehicles never get shifts |
| commissioned_date | date | Y | |  | N | |

## VehicleCapacity — `vehicle_capacity`

Effective-dated capacity versions per vehicle (some vehicles refitted mid-period).

- **Primary key:** capacity_id
- **Foreign keys:** vehicle_id -> vehicle.vehicle_id
- **Cardinality:** Vehicle 1:N VehicleCapacity; VehicleCapacity 1:N Route (version in force on route date)

| field | type | req | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| capacity_id | string | Y | |  | Y | VCAP-\d{6};  |
| vehicle_id | string | Y | |  | N | FK vehicle |
| version | int | Y | |  | N | >=1, increments per vehicle |
| effective_from | date | Y | |  | N | |
| effective_to | date | N | |  | N | inclusive; blank = current; versions must not overlap |
| max_weight_kg | float | Y | | kg | N | |
| max_volume_m3 | float | Y | | m3 | N | |
| max_stops | int | Y | |  | N | >0 |

## Driver — `driver`

Synthetic drivers (pseudonymous labels only, no personal data).

- **Primary key:** driver_id
- **Foreign keys:** none
- **Cardinality:** Driver N:M Vehicle via Shift; Driver 1:N Shift

| field | type | req | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| driver_id | string | Y | |  | Y | DRV-\d{6};  |
| driver_label | string | Y | |  | N | pseudonym 'Driver NNNNNN' |
| license_class | enum | Y | LMV|HMV | | N | |
| max_vehicle_class_rank | int | Y | 2|4 | | N | LMV=2 (vans), HMV=4 (all) |
| hire_date | date | Y | |  | N | |
| status | enum | Y | ACTIVE|INACTIVE | | N | |

## Shift — `shift`

Bridge: driver + vehicle + working window on a date (resolves Driver N:M Vehicle).

- **Primary key:** shift_id
- **Foreign keys:** driver_id -> driver.driver_id, vehicle_id -> vehicle.vehicle_id
- **Cardinality:** Driver 1:N Shift; Vehicle 1:N Shift; Shift 0..1:1 Route (STANDBY shifts have no route)

| field | type | req | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| shift_id | string | Y | |  | Y | SHF-2026-\d{6};  |
| driver_id | string | Y | |  | N | FK driver; one shift per driver per date; driver rank >= vehicle rank |
| vehicle_id | string | Y | |  | N | FK vehicle; one shift per vehicle per date |
| shift_date | date | Y | |  | N | |
| shift_start | datetime | Y | |  | N | |
| shift_end | datetime | Y | |  | N | > shift_start |
| break_minutes | int | Y | | min | N | |
| max_duty_minutes | int | Y | | min | N | = (shift_end-shift_start) - break_minutes |
| shift_status | enum | Y | COMPLETED|STANDBY | | N | |

## TravelTimeMatrix — `travel_time_matrix`

Per-day directed travel matrix over the depot + sites with deliveries that day; 4 time bands; traffic scenario per day.

- **Primary key:** matrix_date, from_site_id, to_site_id
- **Foreign keys:** from_site_id -> customer_site.site_id, to_site_id -> customer_site.site_id
- **Cardinality:** CustomerSite N:M CustomerSite per matrix_date (self pairs included, distance 0)

| field | type | req | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| matrix_date | date | Y | |  | N | |
| from_site_id | string | Y | |  | N | FK customer_site |
| to_site_id | string | Y | |  | N | FK customer_site |
| distance_km | float | Y | | km | N | haversine * circuity(1.20..1.45, seeded, symmetric); constant across days |
| base_minutes | float | Y | | min | N | distance_km / 32 km/h * 60 |
| traffic_scenario | enum | Y | NORMAL|RAIN|EVENT_CONGESTION|HOLIDAY_LIGHT | | N | one per day; Sunday = HOLIDAY_LIGHT |
| scenario_multiplier | float | Y | | x | N | scenario factor * edge-day noise (0.95..1.08) |
| minutes_offpeak | float | Y | | min | N | round(base*mult*1.00,2) |
| minutes_am_peak | float | Y | | min | N | round(base*mult*1.45,2); 07:00-10:00 |
| minutes_midday | float | Y | | min | N | round(base*mult*1.10,2); 10:00-16:30 |
| minutes_pm_peak | float | Y | | min | N | round(base*mult*1.60,2); 16:30-20:00 |

## TimeWindow — `time_window`

Delivery time window (HARD or SOFT) inside site opening hours.

- **Primary key:** tw_id
- **Foreign keys:** delivery_id -> delivery.delivery_id
- **Cardinality:** Delivery 1:1 TimeWindow

| field | type | req | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| tw_id | string | Y | |  | Y | TW-\d{6};  |
| delivery_id | string | Y | |  | Y | FK delivery |
| window_start | datetime | Y | |  | N | on planned_date, >= site.open_time |
| window_end | datetime | Y | |  | N | > window_start, <= site.close_time |
| window_type | enum | Y | HARD|SOFT | | N | |
| grace_minutes | int | Y | | min | N | HARD=15 (refusal beyond), SOFT=30 (planner tolerance) |

## Route — `route`

One vehicle/driver/shift plan for a day with planned totals and simulated actuals.

- **Primary key:** route_id
- **Foreign keys:** vehicle_id -> vehicle.vehicle_id, driver_id -> driver.driver_id, shift_id -> shift.shift_id, vehicle_capacity_id -> vehicle_capacity.capacity_id, depot_site_id -> customer_site.site_id
- **Cardinality:** Shift 1:0..1 Route; Route 1:N RouteStop; Route 1:N Delivery (assigned)

| field | type | req | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| route_id | string | Y | |  | Y | RTE-2026-\d{6};  |
| route_date | date | Y | |  | N | = shift.shift_date |
| vehicle_id | string | Y | |  | N | = shift.vehicle_id |
| driver_id | string | Y | |  | N | = shift.driver_id |
| shift_id | string | Y | |  | Y | |
| vehicle_capacity_id | string | Y | |  | N | capacity version in force on route_date |
| depot_site_id | string | Y | |  | N | |
| capacity_kg_at_plan | float | Y | | kg | N | = vehicle_capacity.max_weight_kg |
| capacity_m3_at_plan | float | Y | | m3 | N | |
| planned_load_kg | float | Y | | kg | N | = SUM(delivery.demand_kg assigned) <= capacity |
| planned_load_m3 | float | Y | | m3 | N | = SUM(delivery volume) <= capacity |
| stop_count | int | Y | |  | N | = COUNT(route_stop); <= max_stops |
| planned_departure | datetime | Y | |  | N | >= shift_start + 20 min |
| planned_return | datetime | Y | |  | N | <= shift_end - 15 min |
| planned_distance_km | float | Y | | km | N | = SUM(leg_distance_km) + return_leg_km |
| planned_drive_minutes | float | Y | | min | N | = SUM(leg_travel_minutes) + return_leg_minutes |
| return_leg_km | float | Y | | km | N | |
| return_leg_minutes | float | Y | | min | N | |
| route_status | enum | Y | COMPLETED | | N | terminal state (history in status_event) |
| actual_departure | datetime | Y | |  | N | |
| actual_return | datetime | Y | |  | N | >= actual_departure; <= shift_end |
| delivered_count | int | Y | |  | N | count of DELIVERED outcomes |
| failed_count | int | Y | |  | N | count of FAILED outcomes; delivered+failed = stop_count |
| load_utilization_pct | float | Y | | % | N | = planned_load_kg / capacity_kg_at_plan * 100 |

## RouteStop — `route_stop`

Ordered stop on a route; one stop serves one delivery.

- **Primary key:** stop_id
- **Foreign keys:** route_id -> route.route_id, delivery_id -> delivery.delivery_id, site_id -> customer_site.site_id
- **Cardinality:** Route 1:N RouteStop; Delivery 1:0..1 RouteStop; RouteStop 1:1 DeliveryOutcome

| field | type | req | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| stop_id | string | Y | |  | Y | STOP-RTE-2026-\d{6}-\d{3}; STOP-<route_id>-<seq> |
| route_id | string | Y | |  | N | |
| stop_sequence | int | Y | |  | N | 1..n contiguous, unique per route |
| delivery_id | string | Y | |  | N | each delivery appears once |
| site_id | string | Y | |  | N | = delivery.site_id |
| planned_arrival | datetime | Y | |  | N | = prev planned_departure + leg_travel_minutes |
| planned_service_start | datetime | Y | |  | N | = max(planned_arrival, window_start) |
| planned_departure | datetime | Y | |  | N | = planned_service_start + service_minutes |
| service_minutes | float | Y | | min | N | |
| leg_distance_km | float | Y | | km | N | = matrix distance(prev,site) |
| leg_travel_minutes | float | Y | | min | N | = matrix minutes in band of prev departure |
| load_after_stop_kg | float | Y | | kg | N | onboard weight after this stop |

## DeliveryOutcome — `delivery_outcome`

Simulated actual result per stop (append-only fact).

- **Primary key:** outcome_id
- **Foreign keys:** stop_id -> route_stop.stop_id, route_id -> route.route_id, delivery_id -> delivery.delivery_id
- **Cardinality:** RouteStop 1:1 DeliveryOutcome

| field | type | req | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| outcome_id | string | Y | |  | Y | OUT-2026-\d{6};  |
| stop_id | string | Y | |  | Y | |
| route_id | string | Y | |  | N | |
| delivery_id | string | Y | |  | N | |
| actual_arrival | datetime | N | |  | N | blank iff NOT_ATTEMPTED; >= previous stop actual_departure |
| actual_service_start | datetime | N | |  | N | blank if failed/not attempted |
| actual_departure | datetime | N | |  | N | |
| outcome_status | enum | Y | DELIVERED|FAILED | | N | |
| reason_code | enum | N | CUSTOMER_ABSENT|ADDRESS_NOT_FOUND|HARD_WINDOW_MISSED|SITE_CLOSED|SHIFT_LIMIT_REACHED | | N | required iff FAILED |
| delay_minutes | float | N | | min | N | = actual_arrival - planned_arrival |
| window_status | enum | Y | WITHIN_WINDOW|EARLY_WAITED|LATE_WITHIN_GRACE|LATE_BREACH|NOT_ATTEMPTED | | N | |
| actual_leg_minutes | float | N | | min | N | |

## StatusEvent (supporting) — `status_event`

Append-only lifecycle history for deliveries and routes; never overwritten.

- **Primary key:** event_id
- **Foreign keys:** none
- **Cardinality:** Delivery 1:N StatusEvent; Route 1:N StatusEvent (polymorphic entity_type/entity_id, validated in code)

| field | type | req | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| event_id | string | Y | |  | Y | EVT-\d{7};  |
| entity_type | enum | Y | DELIVERY|ROUTE | | N | |
| entity_id | string | Y | |  | N | resolves to delivery_id or route_id by entity_type |
| event_seq | int | Y | |  | N | 1.. contiguous per entity |
| from_status | enum | N | CREATED|SCHEDULED|DISPATCHED|DELIVERED|FAILED|UNSERVED|PLANNED|IN_PROGRESS|COMPLETED | | N | |
| to_status | enum | Y | CREATED|SCHEDULED|DISPATCHED|DELIVERED|FAILED|UNSERVED|PLANNED|IN_PROGRESS|COMPLETED | | N | |
| event_ts | datetime | Y | |  | N | non-decreasing per entity |
| actor_role | enum | Y | SYSTEM|PLANNER|CARRIER_OPERATOR|DRIVER | | N | |

## Lifecycle states

- Delivery: CREATED -> SCHEDULED -> DISPATCHED -> DELIVERED | FAILED; CREATED -> UNSERVED
- Route: PLANNED -> DISPATCHED -> IN_PROGRESS -> COMPLETED
- History is append-only in `status_event`; `*_status` columns on parent tables are terminal snapshots.
