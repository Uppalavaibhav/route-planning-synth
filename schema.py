"""Single source of truth: entity definitions -> data dictionary, SQL DDL, validator rules."""
from collections import OrderedDict


def F(name, typ, req=True, allowed="", unit="", unique=False, rule="", pattern=None):
    return dict(name=name, type=typ, required=req, allowed=allowed, unit=unit,
                unique=unique, rule=rule, pattern=pattern)


REASON = "CUSTOMER_ABSENT|ADDRESS_NOT_FOUND|HARD_WINDOW_MISSED|SITE_CLOSED|SHIFT_LIMIT_REACHED"
UNSERVED = "NO_FEASIBLE_VEHICLE|TIME_WINDOW_INFEASIBLE|FLEET_EXHAUSTED"
FINAL = "DELIVERED|FAILED|UNSERVED"
SCEN = "NORMAL|RAIN|EVENT_CONGESTION|HOLIDAY_LIGHT"
EVT_STATES = "CREATED|SCHEDULED|DISPATCHED|DELIVERED|FAILED|UNSERVED|PLANNED|IN_PROGRESS|COMPLETED"

T = OrderedDict()

T["customer_site"] = dict(
    entity="CustomerSite",
    description="Delivery locations (500 customers + 1 depot, SITE-000000) with synthetic geocoordinates and access rules.",
    pk=["site_id"], fks={},
    cardinality=["CustomerSite 1:N Order", "CustomerSite 1:N Delivery", "CustomerSite 1:N RouteStop",
                 "CustomerSite(depot) 1:N Vehicle (home depot)", "CustomerSite N:M CustomerSite via TravelTimeMatrix (per day)"],
    fields=[
        F("site_id", "string", unique=True, pattern=r"SITE-\d{6}", rule="SITE-000000 is the depot; customers SITE-000001.."),
        F("site_name", "string", rule="synthetic label, non-empty"),
        F("site_type", "enum", allowed="CUSTOMER|DEPOT"),
        F("site_category", "enum", allowed="RETAIL|WAREHOUSE|CLINIC|SCHOOL|OFFICE|RESTAURANT|DEPOT"),
        F("zone", "enum", allowed="CENTRAL|NORTH|SOUTH|EAST|WEST", rule="derived from offset to depot (<5 km = CENTRAL)"),
        F("latitude", "float", unit="deg", rule="inside BBOX 17.20..17.60"),
        F("longitude", "float", unit="deg", rule="inside BBOX 78.25..78.65"),
        F("geocode_quality", "enum", allowed="HIGH|MEDIUM|LOW", rule="drives ADDRESS_NOT_FOUND probability"),
        F("max_vehicle_class_rank", "int", allowed="1..4", rule="largest vehicle class rank allowed on site (1=VAN_S..4=TRUCK_H)"),
        F("access_restriction", "enum", allowed="NONE|NO_TRUCK_H|VANS_ONLY", rule="derived: rank4=NONE, rank3=NO_TRUCK_H, rank2=VANS_ONLY"),
        F("open_time", "time", unit="HH:MM", rule="open_time < close_time"),
        F("close_time", "time", unit="HH:MM"),
        F("service_factor", "float", unit="x", rule="0.8..1.6 multiplier on service duration"),
        F("status", "enum", allowed="ACTIVE|INACTIVE"),
        F("effective_from", "date"),
        F("effective_to", "date", req=False, rule="blank = open-ended"),
    ])

T["order"] = dict(
    entity="Order", description="Customer demand. One order is fulfilled by exactly one planned Delivery.",
    pk=["order_id"], fks={"site_id": ("customer_site", "site_id")},
    cardinality=["CustomerSite 1:N Order", "Order 1:1 Delivery"],
    fields=[
        F("order_id", "string", unique=True, pattern=r"ORD-2026-\d{6}"),
        F("site_id", "string", rule="FK customer_site"),
        F("order_date", "date", rule="< requested_date"),
        F("requested_date", "date", rule="= delivery.planned_date"),
        F("demand_kg", "float", unit="kg", rule="> 0"),
        F("demand_volume_m3", "float", unit="m3", rule="> 0; = demand_kg / density(180..450 kg/m3)"),
        F("priority", "enum", allowed="1|2|3", rule="1=urgent, 2=standard, 3=deferrable"),
        F("order_status", "enum", allowed=FINAL, rule="terminal state; = delivery.delivery_status (history in status_event)"),
    ])

T["delivery"] = dict(
    entity="Delivery", description="Planned delivery task for an order; either assigned to a route or explicitly unserved with a reason.",
    pk=["delivery_id"], fks={"order_id": ("order", "order_id"), "site_id": ("customer_site", "site_id"),
                              "assigned_route_id": ("route", "route_id")},
    cardinality=["Order 1:1 Delivery", "Delivery 1:1 TimeWindow", "Route 1:N Delivery (assigned)", "Delivery 0..1:1 RouteStop", "Delivery 0..1:1 DeliveryOutcome"],
    fields=[
        F("delivery_id", "string", unique=True, pattern=r"DEL-2026-\d{6}"),
        F("order_id", "string", unique=True, rule="FK order"),
        F("site_id", "string", rule="FK customer_site; = order.site_id"),
        F("planned_date", "date"),
        F("demand_kg", "float", unit="kg", rule="= order.demand_kg"),
        F("demand_volume_m3", "float", unit="m3", rule="= order.demand_volume_m3"),
        F("priority", "enum", allowed="1|2|3", rule="= order.priority"),
        F("service_minutes", "float", unit="min", rule="clip((6+0.012*kg)*site.service_factor, 5, 60)"),
        F("assignment_status", "enum", allowed="ASSIGNED|UNSERVED"),
        F("assigned_route_id", "string", req=False, rule="required iff ASSIGNED"),
        F("unserved_reason_code", "enum", req=False, allowed=UNSERVED, rule="required iff UNSERVED"),
        F("delivery_status", "enum", allowed=FINAL, rule="terminal state of lifecycle"),
    ])

T["vehicle"] = dict(
    entity="Vehicle", description="Fleet vehicles (4 classes) based at the depot.",
    pk=["vehicle_id"], fks={"depot_site_id": ("customer_site", "site_id")},
    cardinality=["Vehicle 1:N VehicleCapacity (effective-dated)", "Vehicle N:M Driver via Shift", "Vehicle 1:N Route"],
    fields=[
        F("vehicle_id", "string", unique=True, pattern=r"VEH-\d{6}"),
        F("registration_no", "string", unique=True, rule="synthetic plate"),
        F("vehicle_class", "enum", allowed="VAN_S|VAN_L|TRUCK_M|TRUCK_H"),
        F("class_rank", "int", allowed="1..4", rule="VAN_S=1, VAN_L=2, TRUCK_M=3, TRUCK_H=4"),
        F("cost_per_km", "float", unit="INR/km"),
        F("fixed_cost_per_day", "float", unit="INR"),
        F("depot_site_id", "string", rule="FK customer_site (DEPOT)"),
        F("status", "enum", allowed="ACTIVE|MAINTENANCE", rule="MAINTENANCE vehicles never get shifts"),
        F("commissioned_date", "date"),
    ])

T["vehicle_capacity"] = dict(
    entity="VehicleCapacity", description="Effective-dated capacity versions per vehicle (some vehicles refitted mid-period).",
    pk=["capacity_id"], fks={"vehicle_id": ("vehicle", "vehicle_id")},
    cardinality=["Vehicle 1:N VehicleCapacity", "VehicleCapacity 1:N Route (version in force on route date)"],
    fields=[
        F("capacity_id", "string", unique=True, pattern=r"VCAP-\d{6}"),
        F("vehicle_id", "string", rule="FK vehicle"),
        F("version", "int", rule=">=1, increments per vehicle"),
        F("effective_from", "date"),
        F("effective_to", "date", req=False, rule="inclusive; blank = current; versions must not overlap"),
        F("max_weight_kg", "float", unit="kg"),
        F("max_volume_m3", "float", unit="m3"),
        F("max_stops", "int", rule=">0"),
    ])

T["driver"] = dict(
    entity="Driver", description="Synthetic drivers (pseudonymous labels only, no personal data).",
    pk=["driver_id"], fks={},
    cardinality=["Driver N:M Vehicle via Shift", "Driver 1:N Shift"],
    fields=[
        F("driver_id", "string", unique=True, pattern=r"DRV-\d{6}"),
        F("driver_label", "string", rule="pseudonym 'Driver NNNNNN'"),
        F("license_class", "enum", allowed="LMV|HMV"),
        F("max_vehicle_class_rank", "int", allowed="2|4", rule="LMV=2 (vans), HMV=4 (all)"),
        F("hire_date", "date"),
        F("status", "enum", allowed="ACTIVE|INACTIVE"),
    ])

T["shift"] = dict(
    entity="Shift", description="Bridge: driver + vehicle + working window on a date (resolves Driver N:M Vehicle).",
    pk=["shift_id"], fks={"driver_id": ("driver", "driver_id"), "vehicle_id": ("vehicle", "vehicle_id")},
    cardinality=["Driver 1:N Shift", "Vehicle 1:N Shift", "Shift 0..1:1 Route (STANDBY shifts have no route)"],
    fields=[
        F("shift_id", "string", unique=True, pattern=r"SHF-2026-\d{6}"),
        F("driver_id", "string", rule="FK driver; one shift per driver per date; driver rank >= vehicle rank"),
        F("vehicle_id", "string", rule="FK vehicle; one shift per vehicle per date"),
        F("shift_date", "date"),
        F("shift_start", "datetime"),
        F("shift_end", "datetime", rule="> shift_start"),
        F("break_minutes", "int", unit="min"),
        F("max_duty_minutes", "int", unit="min", rule="= (shift_end-shift_start) - break_minutes"),
        F("shift_status", "enum", allowed="COMPLETED|STANDBY"),
    ])

T["travel_time_matrix"] = dict(
    entity="TravelTimeMatrix",
    description="Per-day directed travel matrix over the depot + sites with deliveries that day; 4 time bands; traffic scenario per day.",
    pk=["matrix_date", "from_site_id", "to_site_id"],
    fks={"from_site_id": ("customer_site", "site_id"), "to_site_id": ("customer_site", "site_id")},
    cardinality=["CustomerSite N:M CustomerSite per matrix_date (self pairs included, distance 0)"],
    fields=[
        F("matrix_date", "date"),
        F("from_site_id", "string", rule="FK customer_site"),
        F("to_site_id", "string", rule="FK customer_site"),
        F("distance_km", "float", unit="km", rule="haversine * circuity(1.20..1.45, seeded, symmetric); constant across days"),
        F("base_minutes", "float", unit="min", rule="distance_km / 32 km/h * 60"),
        F("traffic_scenario", "enum", allowed=SCEN, rule="one per day; Sunday = HOLIDAY_LIGHT"),
        F("scenario_multiplier", "float", unit="x", rule="scenario factor * edge-day noise (0.95..1.08)"),
        F("minutes_offpeak", "float", unit="min", rule="round(base*mult*1.00,2)"),
        F("minutes_am_peak", "float", unit="min", rule="round(base*mult*1.45,2); 07:00-10:00"),
        F("minutes_midday", "float", unit="min", rule="round(base*mult*1.10,2); 10:00-16:30"),
        F("minutes_pm_peak", "float", unit="min", rule="round(base*mult*1.60,2); 16:30-20:00"),
    ])

T["time_window"] = dict(
    entity="TimeWindow", description="Delivery time window (HARD or SOFT) inside site opening hours.",
    pk=["tw_id"], fks={"delivery_id": ("delivery", "delivery_id")},
    cardinality=["Delivery 1:1 TimeWindow"],
    fields=[
        F("tw_id", "string", unique=True, pattern=r"TW-\d{6}"),
        F("delivery_id", "string", unique=True, rule="FK delivery"),
        F("window_start", "datetime", rule="on planned_date, >= site.open_time"),
        F("window_end", "datetime", rule="> window_start, <= site.close_time"),
        F("window_type", "enum", allowed="HARD|SOFT"),
        F("grace_minutes", "int", unit="min", rule="HARD=15 (refusal beyond), SOFT=30 (planner tolerance)"),
    ])

T["route"] = dict(
    entity="Route", description="One vehicle/driver/shift plan for a day with planned totals and simulated actuals.",
    pk=["route_id"], fks={"vehicle_id": ("vehicle", "vehicle_id"), "driver_id": ("driver", "driver_id"),
                          "shift_id": ("shift", "shift_id"), "vehicle_capacity_id": ("vehicle_capacity", "capacity_id"),
                          "depot_site_id": ("customer_site", "site_id")},
    cardinality=["Shift 1:0..1 Route", "Route 1:N RouteStop", "Route 1:N Delivery (assigned)"],
    fields=[
        F("route_id", "string", unique=True, pattern=r"RTE-2026-\d{6}"),
        F("route_date", "date", rule="= shift.shift_date"),
        F("vehicle_id", "string", rule="= shift.vehicle_id"),
        F("driver_id", "string", rule="= shift.driver_id"),
        F("shift_id", "string", unique=True),
        F("vehicle_capacity_id", "string", rule="capacity version in force on route_date"),
        F("depot_site_id", "string"),
        F("capacity_kg_at_plan", "float", unit="kg", rule="= vehicle_capacity.max_weight_kg"),
        F("capacity_m3_at_plan", "float", unit="m3"),
        F("planned_load_kg", "float", unit="kg", rule="= SUM(delivery.demand_kg assigned) <= capacity"),
        F("planned_load_m3", "float", unit="m3", rule="= SUM(delivery volume) <= capacity"),
        F("stop_count", "int", rule="= COUNT(route_stop); <= max_stops"),
        F("planned_departure", "datetime", rule=">= shift_start + 20 min"),
        F("planned_return", "datetime", rule="<= shift_end - 15 min"),
        F("planned_distance_km", "float", unit="km", rule="= SUM(leg_distance_km) + return_leg_km"),
        F("planned_drive_minutes", "float", unit="min", rule="= SUM(leg_travel_minutes) + return_leg_minutes"),
        F("return_leg_km", "float", unit="km"),
        F("return_leg_minutes", "float", unit="min"),
        F("route_status", "enum", allowed="COMPLETED", rule="terminal state (history in status_event)"),
        F("actual_departure", "datetime"),
        F("actual_return", "datetime", rule=">= actual_departure; <= shift_end"),
        F("delivered_count", "int", rule="count of DELIVERED outcomes"),
        F("failed_count", "int", rule="count of FAILED outcomes; delivered+failed = stop_count"),
        F("load_utilization_pct", "float", unit="%", rule="= planned_load_kg / capacity_kg_at_plan * 100"),
    ])

T["route_stop"] = dict(
    entity="RouteStop", description="Ordered stop on a route; one stop serves one delivery.",
    pk=["stop_id"], fks={"route_id": ("route", "route_id"), "delivery_id": ("delivery", "delivery_id"),
                         "site_id": ("customer_site", "site_id")},
    cardinality=["Route 1:N RouteStop", "Delivery 1:0..1 RouteStop", "RouteStop 1:1 DeliveryOutcome"],
    fields=[
        F("stop_id", "string", unique=True, pattern=r"STOP-RTE-2026-\d{6}-\d{3}", rule="STOP-<route_id>-<seq>"),
        F("route_id", "string"),
        F("stop_sequence", "int", rule="1..n contiguous, unique per route"),
        F("delivery_id", "string", rule="each delivery appears once"),
        F("site_id", "string", rule="= delivery.site_id"),
        F("planned_arrival", "datetime", rule="= prev planned_departure + leg_travel_minutes"),
        F("planned_service_start", "datetime", rule="= max(planned_arrival, window_start)"),
        F("planned_departure", "datetime", rule="= planned_service_start + service_minutes"),
        F("service_minutes", "float", unit="min"),
        F("leg_distance_km", "float", unit="km", rule="= matrix distance(prev,site)"),
        F("leg_travel_minutes", "float", unit="min", rule="= matrix minutes in band of prev departure"),
        F("load_after_stop_kg", "float", unit="kg", rule="onboard weight after this stop"),
    ])

T["delivery_outcome"] = dict(
    entity="DeliveryOutcome", description="Simulated actual result per stop (append-only fact).",
    pk=["outcome_id"], fks={"stop_id": ("route_stop", "stop_id"), "route_id": ("route", "route_id"),
                            "delivery_id": ("delivery", "delivery_id")},
    cardinality=["RouteStop 1:1 DeliveryOutcome"],
    fields=[
        F("outcome_id", "string", unique=True, pattern=r"OUT-2026-\d{6}"),
        F("stop_id", "string", unique=True),
        F("route_id", "string"),
        F("delivery_id", "string"),
        F("actual_arrival", "datetime", req=False, rule="blank iff NOT_ATTEMPTED; >= previous stop actual_departure"),
        F("actual_service_start", "datetime", req=False, rule="blank if failed/not attempted"),
        F("actual_departure", "datetime", req=False),
        F("outcome_status", "enum", allowed="DELIVERED|FAILED"),
        F("reason_code", "enum", req=False, allowed=REASON, rule="required iff FAILED"),
        F("delay_minutes", "float", req=False, unit="min", rule="= actual_arrival - planned_arrival"),
        F("window_status", "enum", allowed="WITHIN_WINDOW|EARLY_WAITED|LATE_WITHIN_GRACE|LATE_BREACH|NOT_ATTEMPTED"),
        F("actual_leg_minutes", "float", req=False, unit="min"),
    ])

T["status_event"] = dict(
    entity="StatusEvent (supporting)", description="Append-only lifecycle history for deliveries and routes; never overwritten.",
    pk=["event_id"], fks={},
    cardinality=["Delivery 1:N StatusEvent", "Route 1:N StatusEvent (polymorphic entity_type/entity_id, validated in code)"],
    fields=[
        F("event_id", "string", unique=True, pattern=r"EVT-\d{7}"),
        F("entity_type", "enum", allowed="DELIVERY|ROUTE"),
        F("entity_id", "string", rule="resolves to delivery_id or route_id by entity_type"),
        F("event_seq", "int", rule="1.. contiguous per entity"),
        F("from_status", "enum", req=False, allowed=EVT_STATES),
        F("to_status", "enum", allowed=EVT_STATES),
        F("event_ts", "datetime", rule="non-decreasing per entity"),
        F("actor_role", "enum", allowed="SYSTEM|PLANNER|CARRIER_OPERATOR|DRIVER"),
    ])

TRANSITIONS = {
    "DELIVERY": {None: {"CREATED"}, "CREATED": {"SCHEDULED", "UNSERVED"}, "SCHEDULED": {"DISPATCHED"},
                 "DISPATCHED": {"DELIVERED", "FAILED"}},
    "ROUTE": {None: {"PLANNED"}, "PLANNED": {"DISPATCHED"}, "DISPATCHED": {"IN_PROGRESS"}, "IN_PROGRESS": {"COMPLETED"}},
}
TABLE_ORDER = list(T.keys())
SQL_TYPES = {"string": "TEXT", "int": "INTEGER", "float": "REAL", "date": "TEXT", "datetime": "TEXT",
             "time": "TEXT", "enum": "TEXT"}


def columns(table):
    return [f["name"] for f in T[table]["fields"]]


def enum_values(field):
    return field["allowed"].split("|") if field["type"] == "enum" else None
