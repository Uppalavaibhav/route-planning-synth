PRAGMA foreign_keys = ON;
CREATE TABLE customer_site (
  site_id TEXT NOT NULL,
  site_name TEXT NOT NULL,
  site_type TEXT NOT NULL,
  site_category TEXT NOT NULL,
  zone TEXT NOT NULL,
  latitude REAL NOT NULL,
  longitude REAL NOT NULL,
  geocode_quality TEXT NOT NULL,
  max_vehicle_class_rank INTEGER NOT NULL,
  access_restriction TEXT NOT NULL,
  open_time TEXT NOT NULL,
  close_time TEXT NOT NULL,
  service_factor REAL NOT NULL,
  status TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  PRIMARY KEY (site_id)
);
CREATE TABLE "order" (
  order_id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  order_date TEXT NOT NULL,
  requested_date TEXT NOT NULL,
  demand_kg REAL NOT NULL,
  demand_volume_m3 REAL NOT NULL,
  priority TEXT NOT NULL,
  order_status TEXT NOT NULL,
  PRIMARY KEY (order_id),
  FOREIGN KEY (site_id) REFERENCES customer_site(site_id)
);
CREATE TABLE delivery (
  delivery_id TEXT NOT NULL,
  order_id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  planned_date TEXT NOT NULL,
  demand_kg REAL NOT NULL,
  demand_volume_m3 REAL NOT NULL,
  priority TEXT NOT NULL,
  service_minutes REAL NOT NULL,
  assignment_status TEXT NOT NULL,
  assigned_route_id TEXT,
  unserved_reason_code TEXT,
  delivery_status TEXT NOT NULL,
  PRIMARY KEY (delivery_id),
  FOREIGN KEY (order_id) REFERENCES "order"(order_id),
  FOREIGN KEY (site_id) REFERENCES customer_site(site_id),
  FOREIGN KEY (assigned_route_id) REFERENCES route(route_id)
);
CREATE TABLE vehicle (
  vehicle_id TEXT NOT NULL,
  registration_no TEXT NOT NULL,
  vehicle_class TEXT NOT NULL,
  class_rank INTEGER NOT NULL,
  cost_per_km REAL NOT NULL,
  fixed_cost_per_day REAL NOT NULL,
  depot_site_id TEXT NOT NULL,
  status TEXT NOT NULL,
  commissioned_date TEXT NOT NULL,
  PRIMARY KEY (vehicle_id),
  FOREIGN KEY (depot_site_id) REFERENCES customer_site(site_id)
);
CREATE TABLE vehicle_capacity (
  capacity_id TEXT NOT NULL,
  vehicle_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  max_weight_kg REAL NOT NULL,
  max_volume_m3 REAL NOT NULL,
  max_stops INTEGER NOT NULL,
  PRIMARY KEY (capacity_id),
  FOREIGN KEY (vehicle_id) REFERENCES vehicle(vehicle_id)
);
CREATE TABLE driver (
  driver_id TEXT NOT NULL,
  driver_label TEXT NOT NULL,
  license_class TEXT NOT NULL,
  max_vehicle_class_rank INTEGER NOT NULL,
  hire_date TEXT NOT NULL,
  status TEXT NOT NULL,
  PRIMARY KEY (driver_id)
);
CREATE TABLE shift (
  shift_id TEXT NOT NULL,
  driver_id TEXT NOT NULL,
  vehicle_id TEXT NOT NULL,
  shift_date TEXT NOT NULL,
  shift_start TEXT NOT NULL,
  shift_end TEXT NOT NULL,
  break_minutes INTEGER NOT NULL,
  max_duty_minutes INTEGER NOT NULL,
  shift_status TEXT NOT NULL,
  PRIMARY KEY (shift_id),
  FOREIGN KEY (driver_id) REFERENCES driver(driver_id),
  FOREIGN KEY (vehicle_id) REFERENCES vehicle(vehicle_id)
);
CREATE TABLE travel_time_matrix (
  matrix_date TEXT NOT NULL,
  from_site_id TEXT NOT NULL,
  to_site_id TEXT NOT NULL,
  distance_km REAL NOT NULL,
  base_minutes REAL NOT NULL,
  traffic_scenario TEXT NOT NULL,
  scenario_multiplier REAL NOT NULL,
  minutes_offpeak REAL NOT NULL,
  minutes_am_peak REAL NOT NULL,
  minutes_midday REAL NOT NULL,
  minutes_pm_peak REAL NOT NULL,
  PRIMARY KEY (matrix_date, from_site_id, to_site_id),
  FOREIGN KEY (from_site_id) REFERENCES customer_site(site_id),
  FOREIGN KEY (to_site_id) REFERENCES customer_site(site_id)
);
CREATE TABLE time_window (
  tw_id TEXT NOT NULL,
  delivery_id TEXT NOT NULL,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  window_type TEXT NOT NULL,
  grace_minutes INTEGER NOT NULL,
  PRIMARY KEY (tw_id),
  FOREIGN KEY (delivery_id) REFERENCES delivery(delivery_id)
);
CREATE TABLE route (
  route_id TEXT NOT NULL,
  route_date TEXT NOT NULL,
  vehicle_id TEXT NOT NULL,
  driver_id TEXT NOT NULL,
  shift_id TEXT NOT NULL,
  vehicle_capacity_id TEXT NOT NULL,
  depot_site_id TEXT NOT NULL,
  capacity_kg_at_plan REAL NOT NULL,
  capacity_m3_at_plan REAL NOT NULL,
  planned_load_kg REAL NOT NULL,
  planned_load_m3 REAL NOT NULL,
  stop_count INTEGER NOT NULL,
  planned_departure TEXT NOT NULL,
  planned_return TEXT NOT NULL,
  planned_distance_km REAL NOT NULL,
  planned_drive_minutes REAL NOT NULL,
  return_leg_km REAL NOT NULL,
  return_leg_minutes REAL NOT NULL,
  route_status TEXT NOT NULL,
  actual_departure TEXT NOT NULL,
  actual_return TEXT NOT NULL,
  delivered_count INTEGER NOT NULL,
  failed_count INTEGER NOT NULL,
  load_utilization_pct REAL NOT NULL,
  PRIMARY KEY (route_id),
  FOREIGN KEY (vehicle_id) REFERENCES vehicle(vehicle_id),
  FOREIGN KEY (driver_id) REFERENCES driver(driver_id),
  FOREIGN KEY (shift_id) REFERENCES shift(shift_id),
  FOREIGN KEY (vehicle_capacity_id) REFERENCES vehicle_capacity(capacity_id),
  FOREIGN KEY (depot_site_id) REFERENCES customer_site(site_id)
);
CREATE TABLE route_stop (
  stop_id TEXT NOT NULL,
  route_id TEXT NOT NULL,
  stop_sequence INTEGER NOT NULL,
  delivery_id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  planned_arrival TEXT NOT NULL,
  planned_service_start TEXT NOT NULL,
  planned_departure TEXT NOT NULL,
  service_minutes REAL NOT NULL,
  leg_distance_km REAL NOT NULL,
  leg_travel_minutes REAL NOT NULL,
  load_after_stop_kg REAL NOT NULL,
  PRIMARY KEY (stop_id),
  FOREIGN KEY (route_id) REFERENCES route(route_id),
  FOREIGN KEY (delivery_id) REFERENCES delivery(delivery_id),
  FOREIGN KEY (site_id) REFERENCES customer_site(site_id)
);
CREATE TABLE delivery_outcome (
  outcome_id TEXT NOT NULL,
  stop_id TEXT NOT NULL,
  route_id TEXT NOT NULL,
  delivery_id TEXT NOT NULL,
  actual_arrival TEXT,
  actual_service_start TEXT,
  actual_departure TEXT,
  outcome_status TEXT NOT NULL,
  reason_code TEXT,
  delay_minutes REAL,
  window_status TEXT NOT NULL,
  actual_leg_minutes REAL,
  PRIMARY KEY (outcome_id),
  FOREIGN KEY (stop_id) REFERENCES route_stop(stop_id),
  FOREIGN KEY (route_id) REFERENCES route(route_id),
  FOREIGN KEY (delivery_id) REFERENCES delivery(delivery_id)
);
CREATE TABLE status_event (
  event_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  event_seq INTEGER NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  event_ts TEXT NOT NULL,
  actor_role TEXT NOT NULL,
  PRIMARY KEY (event_id)
);
