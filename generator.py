#!/usr/bin/env python3
"""Deterministic synthetic data generator: delivery planning across vehicles, stops, time windows,
capacities and driver shifts.  Same generator for every scale (see SCALES).

  python generator.py --scale full --seed 20261022 --out data/full
"""
import argparse, copy, csv, datetime as dt, hashlib, json, math, os, random, shlex, sys
from collections import defaultdict

import schema, validate
from common import *

SCALES = {
    "starter": dict(sites=50, deliveries=200, vehicles=12, days=5),
    "full": dict(sites=500, deliveries=2000, vehicles=100, days=30),
}
START = dt.date(2026, 10, 1)
CLASSES = [
    dict(cls="VAN_S", rank=1, kg=800.0, m3=5.0, stops=12, cpk=9.0, fixed=900.0, w=0.35),
    dict(cls="VAN_L", rank=2, kg=1500.0, m3=11.0, stops=15, cpk=12.5, fixed=1300.0, w=0.30),
    dict(cls="TRUCK_M", rank=3, kg=4000.0, m3=24.0, stops=18, cpk=21.0, fixed=2200.0, w=0.22),
    dict(cls="TRUCK_H", rank=4, kg=8000.0, m3=45.0, stops=20, cpk=32.0, fixed=3600.0, w=0.13),
]


def R(cfg, name):
    return random.Random(f"{cfg['seed']}:{name}")


def ts(day, minutes):
    base = dt.datetime.combine(day, dt.time(0))
    return (base + dt.timedelta(seconds=round(minutes * 60))).isoformat(timespec="seconds")


def hhmm(m):
    return f"{int(m // 60):02d}:{int(m % 60):02d}"


def tmin(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def zone_of(lat, lon):
    dy, dx = (lat - DEPOT_LL[0]) * 111.0, (lon - DEPOT_LL[1]) * 106.0
    if math.hypot(dx, dy) < 5.0:
        return "CENTRAL"
    if abs(dy) >= abs(dx):
        return "NORTH" if dy > 0 else "SOUTH"
    return "EAST" if dx > 0 else "WEST"


# ------------------------------------------------------------------ master data
def gen_sites(cfg):
    r = R(cfg, "sites")
    rows = [dict(site_id=DEPOT_ID, site_name="Central Depot", site_type="DEPOT", site_category="DEPOT",
                 zone="CENTRAL", latitude=DEPOT_LL[0], longitude=DEPOT_LL[1], geocode_quality="HIGH",
                 max_vehicle_class_rank=4, access_restriction="NONE", open_time="00:00", close_time="23:59",
                 service_factor=1.0, status="ACTIVE", effective_from="2026-01-01", effective_to=None)]
    centres = [(r.uniform(17.28, 17.52), r.uniform(78.32, 78.58)) for _ in range(8)]
    cats = ["RETAIL", "WAREHOUSE", "CLINIC", "SCHOOL", "OFFICE", "RESTAURANT"]
    hours = [("07:00", "20:00"), ("08:00", "18:00"), ("09:00", "17:00"), ("10:00", "21:00"), ("08:00", "20:00")]
    seen = set()
    for i in range(1, cfg["sites"] + 1):
        while True:
            c = r.choice(centres)
            lat = round(min(max(r.gauss(c[0], 0.035), BBOX["lat_min"] + .005), BBOX["lat_max"] - .005), 6)
            lon = round(min(max(r.gauss(c[1], 0.035), BBOX["lon_min"] + .005), BBOX["lon_max"] - .005), 6)
            if (lat, lon) not in seen:
                seen.add((lat, lon)); break
        x = r.random()
        rank = 2 if x < 0.12 else 3 if x < 0.30 else 4
        q = r.random()
        o, c_ = r.choice(hours)
        cat = r.choices(cats, [30, 10, 12, 10, 25, 13])[0]
        rows.append(dict(
            site_id=f"SITE-{i:06d}", site_name=f"{cat.title()} Outlet {i:04d}", site_type="CUSTOMER",
            site_category=cat, zone=zone_of(lat, lon), latitude=lat, longitude=lon,
            geocode_quality="HIGH" if q < 0.85 else "MEDIUM" if q < 0.97 else "LOW",
            max_vehicle_class_rank=rank, access_restriction={4: "NONE", 3: "NO_TRUCK_H", 2: "VANS_ONLY"}[rank],
            open_time=o, close_time=c_, service_factor=round(r.uniform(0.8, 1.6), 2), status="ACTIVE",
            effective_from="2026-01-01", effective_to=None))
    return rows


def min_rank(kg, m3):
    for c in CLASSES:
        if kg <= c["kg"] and m3 <= c["m3"]:
            return c["rank"]
    return 5


def gen_orders_deliveries(cfg, sites):
    r = R(cfg, "orders")
    custs = [s for s in sites if s["site_type"] == "CUSTOMER"]
    days = [START + dt.timedelta(d) for d in range(cfg["days"])]
    dw = [0.25 if d.weekday() == 6 else 0.7 if d.weekday() == 5 else 1.0 for d in days]
    sw = [1.0 / (1 + i / 50) ** 0.8 for i in range(len(custs))]
    recs = []
    for _ in range(cfg["deliveries"]):
        pdate = r.choices(days, dw)[0]
        s = r.choices(custs, sw)[0]
        odate = pdate - dt.timedelta(days=r.randint(1, 5))
        bulk = r.random() < 0.05
        kg = r.uniform(1500, 6000) if bulk else min(max(r.lognormvariate(math.log(250), 0.8), 10), 1450)
        kg = round(kg, 1)
        m3 = round(kg / r.uniform(180, 450), 3)
        pr = r.choices([1, 2, 3], [0.10, 0.70, 0.20])[0]
        svc = round(min(max((6 + 0.012 * kg) * s["service_factor"], 5), 60), 1)
        o, c = tmin(s["open_time"]), tmin(s["close_time"])
        width = min(r.choices([120, 180, 240, 360], [30, 30, 25, 15])[0], c - o)
        start = o + 30 * r.randint(0, int((c - width - o) // 30))
        wtype = "HARD" if (pr == 1 or (pr == 2 and r.random() < 0.85) or (pr == 3 and r.random() < 0.2)) else "SOFT"
        recs.append(dict(pdate=pdate, odate=odate, site=s, kg=kg, m3=m3, pr=pr, svc=svc,
                         tw_s=start, tw_e=start + width, wtype=wtype, tie=r.random()))
    recs.sort(key=lambda x: (x["odate"], x["pdate"], x["tie"]))
    orders, deliveries, tws = [], [], []
    for i, x in enumerate(recs, 1):
        oid, did = f"ORD-2026-{i:06d}", f"DEL-2026-{i:06d}"
        sid = x["site"]["site_id"]
        orders.append(dict(order_id=oid, site_id=sid, order_date=x["odate"].isoformat(),
                           requested_date=x["pdate"].isoformat(), demand_kg=x["kg"], demand_volume_m3=x["m3"],
                           priority=x["pr"], order_status=None))
        deliveries.append(dict(delivery_id=did, order_id=oid, site_id=sid, planned_date=x["pdate"].isoformat(),
                               demand_kg=x["kg"], demand_volume_m3=x["m3"], priority=x["pr"],
                               service_minutes=x["svc"], assignment_status=None, assigned_route_id=None,
                               unserved_reason_code=None, delivery_status=None,
                               _tw_s=x["tw_s"], _tw_e=x["tw_e"], _tw_type=x["wtype"], _pdate=x["pdate"]))
        tws.append(dict(tw_id=f"TW-{i:06d}", delivery_id=did, window_start=ts(x["pdate"], x["tw_s"]),
                        window_end=ts(x["pdate"], x["tw_e"]), window_type=x["wtype"],
                        grace_minutes=HARD_GRACE if x["wtype"] == "HARD" else SOFT_GRACE))
    return orders, deliveries, tws


def gen_fleet(cfg):
    r = R(cfg, "fleet")
    n = cfg["vehicles"]
    counts = [round(n * c["w"]) for c in CLASSES[:3]]
    counts.append(n - sum(counts))
    cl = []
    for c, k in zip(CLASSES, counts):
        cl += [c] * k
    r.shuffle(cl)
    refit_day = START + dt.timedelta(days=min(14, max(1, cfg["days"] // 2)))
    vehicles, caps = [], []
    active = defaultdict(int)
    for i, c in enumerate(cl, 1):
        vehicles.append(dict(vehicle_id=f"VEH-{i:06d}", registration_no=f"TS09ZZ{i:04d}", vehicle_class=c["cls"],
                             class_rank=c["rank"], cost_per_km=c["cpk"], fixed_cost_per_day=c["fixed"],
                             depot_site_id=DEPOT_ID, status="ACTIVE",
                             commissioned_date=(dt.date(2019, 1, 1) + dt.timedelta(days=r.randint(0, 2300))).isoformat()))
        active[c["cls"]] += 1
    for v in vehicles:
        if r.random() < 0.05 and active[v["vehicle_class"]] > 1:
            v["status"] = "MAINTENANCE"; active[v["vehicle_class"]] -= 1
    k = 0
    for v in vehicles:
        c = next(c for c in CLASSES if c["cls"] == v["vehicle_class"])
        k += 1
        refit = v["status"] == "ACTIVE" and r.random() < 0.12
        caps.append(dict(capacity_id=f"VCAP-{k:06d}", vehicle_id=v["vehicle_id"], version=1,
                         effective_from="2026-01-01",
                         effective_to=(refit_day - dt.timedelta(days=1)).isoformat() if refit else None,
                         max_weight_kg=c["kg"], max_volume_m3=c["m3"], max_stops=c["stops"]))
        if refit:
            k += 1
            caps.append(dict(capacity_id=f"VCAP-{k:06d}", vehicle_id=v["vehicle_id"], version=2,
                             effective_from=refit_day.isoformat(), effective_to=None,
                             max_weight_kg=round(c["kg"] * 0.92, 1), max_volume_m3=round(c["m3"] * 0.92, 2),
                             max_stops=c["stops"]))
    return vehicles, caps


def gen_drivers(cfg):
    r = R(cfg, "drivers")
    n = math.ceil(cfg["vehicles"] * 1.2)
    n_hmv = round(n * 0.5)
    lic = ["HMV"] * n_hmv + ["LMV"] * (n - n_hmv)
    r.shuffle(lic)
    return [dict(driver_id=f"DRV-{i:06d}", driver_label=f"Driver {i:06d}", license_class=l,
                 max_vehicle_class_rank=4 if l == "HMV" else 2,
                 hire_date=(dt.date(2015, 1, 1) + dt.timedelta(days=r.randint(0, 3800))).isoformat(), status="ACTIVE")
            for i, l in enumerate(lic, 1)]


# ------------------------------------------------------------------ matrices
def day_matrix(cfg, day, nodes, site_ll, scen):
    """Returns (dict[(a,b)] -> (dist,[4 band minutes],base,mult), rows)"""
    seed, dd = cfg["seed"], day.isoformat()
    tt, rows = {}, []
    for a in nodes:
        for b in nodes:
            dist = road_km(seed, a, site_ll[a], b, site_ll[b])
            base = base_minutes(dist)
            mult = round(SCEN_MULT[scen] * (0.95 + 0.13 * det(seed, "edge", dd, a, b)), 4) if a != b else 1.0
            mins = [band_minutes(base, mult, i) for i in range(4)]
            tt[(a, b)] = (dist, mins, base, mult)
            rows.append(dict(matrix_date=dd, from_site_id=a, to_site_id=b, distance_km=dist, base_minutes=base,
                             traffic_scenario=scen, scenario_multiplier=mult, minutes_offpeak=mins[0],
                             minutes_am_peak=mins[1], minutes_midday=mins[2], minutes_pm_peak=mins[3]))
    return tt, rows


# ------------------------------------------------------------------ planner
def schedule(items, sh, tt, S):
    """Evaluate a stop sequence; None if any constraint is violated."""
    base = sh["_s"] + LOAD_MIN
    leg1 = tt[(DEPOT_ID, items[0]["site_id"])][1][band_index(base)]
    t = max(base, items[0]["_tw_s"] - leg1)
    t0, prev, dist, drive, stops = t, DEPOT_ID, 0.0, 0.0, []
    for d in items:
        e = tt[(prev, d["site_id"])]
        leg = e[1][band_index(t)]
        arr = t + leg
        if arr > d["_tw_e"] + (0 if d["_tw_type"] == "HARD" else SOFT_GRACE):
            return None
        start = max(arr, d["_tw_s"])
        dep = start + d["service_minutes"]
        if dep > S[d["site_id"]]["_close"]:
            return None
        stops.append(dict(d=d, arr=arr, start=start, dep=dep, leg=leg, ldist=e[0]))
        dist += e[0]; drive += leg; t = dep; prev = d["site_id"]
    e = tt[(prev, DEPOT_ID)]
    rl = e[1][band_index(t)]
    if t + rl > sh["_e"] - RETURN_BUFFER:
        return None
    return dict(stops=stops, t0=t0, ret=t + rl, ret_leg=rl, ret_dist=e[0], dist=dist + e[0], drive=drive + rl)


def plan_day(items, shifts, tt, S):
    order = sorted(items, key=lambda d: (d["priority"], d["_tw_e"], d["delivery_id"]))
    routes, unused, unserved = [], list(shifts), {}

    def veh_ok(sh, d):
        c = sh["_cap"]
        return (sh["_veh"]["class_rank"] <= S[d["site_id"]]["max_vehicle_class_rank"]
                and d["demand_kg"] <= c["max_weight_kg"] and d["demand_volume_m3"] <= c["max_volume_m3"])

    for d in order:
        best = None
        for r in routes:
            c = r["sh"]["_cap"]
            if (S[d["site_id"]]["max_vehicle_class_rank"] < r["sh"]["_veh"]["class_rank"]
                    or r["kg"] + d["demand_kg"] > c["max_weight_kg"] or r["m3"] + d["demand_volume_m3"] > c["max_volume_m3"]
                    or len(r["items"]) >= c["max_stops"]):
                continue
            for pos in range(len(r["items"]) + 1):
                res = schedule(r["items"][:pos] + [d] + r["items"][pos:], r["sh"], tt, S)
                if res:
                    cost = res["dist"] - r["plan"]["dist"]
                    if best is None or cost < best[0] - 1e-9:
                        best = (cost, r, pos, res)
        if best:
            _, r, pos, res = best
            r["items"].insert(pos, d); r["plan"] = res
            r["kg"] += d["demand_kg"]; r["m3"] += d["demand_volume_m3"]
            continue
        opened = False
        for sh in sorted((s for s in unused if veh_ok(s, d)), key=lambda s: (s["_cap"]["max_weight_kg"], s["shift_id"])):
            res = schedule([d], sh, tt, S)
            if res:
                routes.append(dict(sh=sh, items=[d], plan=res, kg=d["demand_kg"], m3=d["demand_volume_m3"]))
                unused.remove(sh); opened = True; break
        if opened:
            continue
        elig = [s for s in shifts if veh_ok(s, d)]
        if not elig:
            unserved[d["delivery_id"]] = "NO_FEASIBLE_VEHICLE"
        elif all(schedule([d], s, tt, S) is None for s in elig):
            unserved[d["delivery_id"]] = "TIME_WINDOW_INFEASIBLE"
        else:
            unserved[d["delivery_id"]] = "FLEET_EXHAUSTED"
    return routes, unserved


# ------------------------------------------------------------------ simulation (documented outcome rules)
def simulate(rt, tt, S, scen, rng):
    sig = SCEN_SIGMA[scen]
    sh, plan = rt["sh"], rt["plan"]
    dep0 = plan["t0"] + rng.uniform(0, 10)
    prev, prev_dep, ret_prev, aborted, outs = DEPOT_ID, dep0, 0.0, False, []
    for st in plan["stops"]:
        d = st["d"]
        site = S[d["site_id"]]
        o = dict(stop=st, arr=None, start=None, dep=None, status="FAILED", reason="SHIFT_LIMIT_REACHED",
                 delay=None, wstat="NOT_ATTEMPTED", leg=None)
        if not aborted:
            leg_pl = tt[(prev, d["site_id"])][1][band_index(prev_dep)]
            leg = leg_pl * rng.lognormvariate(0, sig) + (rng.uniform(10, 35) if rng.random() < 0.03 else 0.0)
            arr = prev_dep + leg
            delay = arr - st["arr"]
            reason = None
            if arr > site["_close"]:
                reason = "SITE_CLOSED"
            elif d["_tw_type"] == "HARD" and arr > d["_tw_e"] + HARD_GRACE:
                reason = "HARD_WINDOW_MISSED"
            else:
                p_addr = {"LOW": 0.30, "MEDIUM": 0.02, "HIGH": 0.0}[site["geocode_quality"]]
                if rng.random() < p_addr:
                    reason = "ADDRESS_NOT_FOUND"
                elif rng.random() < min(0.20, 0.015 + 0.002 * max(0.0, delay)):
                    reason = "CUSTOMER_ABSENT"
            if reason:
                start, dep = None, arr + 5
            else:
                start = max(arr, d["_tw_s"])
                dep = start + d["service_minutes"] * rng.uniform(0.85, 1.30)
            ret = tt[(d["site_id"], DEPOT_ID)][1][band_index(dep)] * rng.lognormvariate(0, sig)
            if dep + ret > sh["_e"]:
                aborted = True
            else:
                grace = HARD_GRACE if d["_tw_type"] == "HARD" else SOFT_GRACE
                ws = ("EARLY_WAITED" if arr < d["_tw_s"] else "WITHIN_WINDOW" if arr <= d["_tw_e"]
                      else "LATE_WITHIN_GRACE" if arr <= d["_tw_e"] + grace else "LATE_BREACH")
                o.update(arr=arr, start=start, dep=dep, status="FAILED" if reason else "DELIVERED", reason=reason,
                         delay=delay, wstat=ws, leg=leg)
                prev, prev_dep, ret_prev = d["site_id"], dep, ret
        outs.append(o)
    return dep0, prev_dep + ret_prev, outs


# ------------------------------------------------------------------ build
def build(cfg):
    seed = cfg["seed"]
    sites = gen_sites(cfg)
    S = {s["site_id"]: s for s in sites}
    for s in sites:
        s["_close"] = tmin(s["close_time"])
    site_ll = {s["site_id"]: (s["latitude"], s["longitude"]) for s in sites}
    orders, deliveries, tws = gen_orders_deliveries(cfg, sites)
    vehicles, caps = gen_fleet(cfg)
    drivers = gen_drivers(cfg)
    vmap = {v["vehicle_id"]: v for v in vehicles}
    caps_by = defaultdict(list)
    for c in caps:
        caps_by[c["vehicle_id"]].append(c)

    def cap_on(vid, day):
        for c in caps_by[vid]:
            if c["effective_from"] <= day.isoformat() and (c["effective_to"] is None or day.isoformat() <= c["effective_to"]):
                return c

    days = [START + dt.timedelta(d) for d in range(cfg["days"])]
    by_day = defaultdict(list)
    for d in deliveries:
        by_day[d["_pdate"]].append(d)
    rs, rf, rsim = R(cfg, "shifts"), R(cfg, "traffic"), R(cfg, "sim")
    shifts, matrix, routes, stops, outcomes, route_meta = [], [], [], [], [], []
    shift_n = route_n = out_n = 0
    dmap = {d["delivery_id"]: d for d in deliveries}
    for day in days:
        items = by_day[day]
        scen = "HOLIDAY_LIGHT" if day.weekday() == 6 else rf.choices(["NORMAL", "RAIN", "EVENT_CONGESTION"], [70, 15, 15])[0]
        nodes = sorted({DEPOT_ID} | {d["site_id"] for d in items})
        tt, mrows = day_matrix(cfg, day, nodes, site_ll, scen)
        matrix += mrows
        active = [v for v in vehicles if v["status"] == "ACTIVE"]
        n_sh = min(len(active), max(3, math.ceil(len(items) / 2.5)))
        sel = sorted(rs.sample(active, n_sh), key=lambda v: (-v["class_rank"], v["vehicle_id"]))
        pool = list(drivers); rs.shuffle(pool)
        dshifts = []
        for v in sel:
            drv = next((x for x in pool if x["max_vehicle_class_rank"] >= v["class_rank"]), None)
            if drv is None:
                continue
            pool.remove(drv)
            s0 = rs.choice(range(360, 601, 30)); length = rs.choice([480, 540, 600])
            dshifts.append(dict(driver_id=drv["driver_id"], vehicle_id=v["vehicle_id"], shift_date=day.isoformat(),
                                _s=s0, _e=s0 + length, _veh=v, _cap=cap_on(v["vehicle_id"], day), _day=day))
        dshifts.sort(key=lambda s: s["vehicle_id"])
        for s in dshifts:
            shift_n += 1
            s["shift_id"] = f"SHF-2026-{shift_n:06d}"
        rts, unserved = plan_day(items, dshifts, tt, S)
        used = set()
        for did, reason in sorted(unserved.items()):
            d = dmap[did]
            d.update(assignment_status="UNSERVED", unserved_reason_code=reason, delivery_status="UNSERVED")
        for rt in rts:
            route_n += 1
            rid = f"RTE-2026-{route_n:06d}"
            sh, plan = rt["sh"], rt["plan"]
            used.add(sh["shift_id"])
            c = sh["_cap"]
            for k, st in enumerate(plan["stops"], 1):
                st["stop_id"] = f"STOP-{rid}-{k:03d}"
                st["seq"] = k
            dep0, act_ret, outs = simulate(rt, tt, S, scen, rsim)
            load = round(sum(d["demand_kg"] for d in rt["items"]), 1)
            m3 = round(sum(d["demand_volume_m3"] for d in rt["items"]), 3)
            rem, delivered, failed = load, 0, 0
            for st, o in zip(plan["stops"], outs):
                d = st["d"]
                rem = round(rem - d["demand_kg"], 1)
                stops.append(dict(stop_id=st["stop_id"], route_id=rid, stop_sequence=st["seq"], delivery_id=d["delivery_id"],
                                  site_id=d["site_id"], planned_arrival=ts(day, st["arr"]),
                                  planned_service_start=ts(day, st["start"]), planned_departure=ts(day, st["dep"]),
                                  service_minutes=d["service_minutes"], leg_distance_km=st["ldist"],
                                  leg_travel_minutes=st["leg"], load_after_stop_kg=rem))
                out_n += 1
                outcomes.append(dict(
                    outcome_id=f"OUT-2026-{out_n:06d}", stop_id=st["stop_id"], route_id=rid, delivery_id=d["delivery_id"],
                    actual_arrival=ts(day, o["arr"]) if o["arr"] is not None else None,
                    actual_service_start=ts(day, o["start"]) if o["start"] is not None else None,
                    actual_departure=ts(day, o["dep"]) if o["dep"] is not None else None,
                    outcome_status=o["status"], reason_code=o["reason"],
                    delay_minutes=round(o["arr"] - st["arr"], 2) if o["arr"] is not None else None,
                    window_status=o["wstat"], actual_leg_minutes=round(o["leg"], 2) if o["leg"] is not None else None))
                d.update(assignment_status="ASSIGNED", assigned_route_id=rid, delivery_status=o["status"])
                delivered += o["status"] == "DELIVERED"; failed += o["status"] == "FAILED"
            routes.append(dict(
                route_id=rid, route_date=day.isoformat(), vehicle_id=sh["vehicle_id"], driver_id=sh["driver_id"],
                shift_id=sh["shift_id"], vehicle_capacity_id=c["capacity_id"], depot_site_id=DEPOT_ID,
                capacity_kg_at_plan=c["max_weight_kg"], capacity_m3_at_plan=c["max_volume_m3"], planned_load_kg=load,
                planned_load_m3=m3, stop_count=len(plan["stops"]), planned_departure=ts(day, plan["t0"]),
                planned_return=ts(day, plan["ret"]), planned_distance_km=round(plan["dist"], 3),
                planned_drive_minutes=round(plan["drive"], 2), return_leg_km=plan["ret_dist"],
                return_leg_minutes=plan["ret_leg"], route_status="COMPLETED", actual_departure=ts(day, dep0),
                actual_return=ts(day, act_ret), delivered_count=delivered, failed_count=failed,
                load_utilization_pct=round(load / c["max_weight_kg"] * 100, 2)))
        for s in dshifts:
            shifts.append(dict(shift_id=s["shift_id"], driver_id=s["driver_id"], vehicle_id=s["vehicle_id"],
                               shift_date=s["shift_date"], shift_start=ts(day, s["_s"]), shift_end=ts(day, s["_e"]),
                               break_minutes=30, max_duty_minutes=s["_e"] - s["_s"] - 30,
                               shift_status="COMPLETED" if s["shift_id"] in used else "STANDBY"))
    dstat = {d["order_id"]: d["delivery_status"] for d in deliveries}
    for o in orders:
        o["order_status"] = dstat[o["order_id"]]
    events = gen_events(deliveries, routes, outcomes, orders)
    for d in deliveries:
        for k in [k for k in d if k.startswith("_")]:
            del d[k]
    for s in sites:
        s.pop("_close", None)
    return dict(customer_site=sites, order=orders, delivery=deliveries, vehicle=vehicles, vehicle_capacity=caps,
                driver=drivers, shift=shifts, travel_time_matrix=matrix, time_window=tws, route=routes,
                route_stop=stops, delivery_outcome=outcomes, status_event=events)


def gen_events(deliveries, routes, outcomes, orders):
    odate = {o["order_id"]: o["order_date"] for o in orders}
    rmap = {r["route_id"]: r for r in routes}
    omap = {o["delivery_id"]: o for o in outcomes}
    ev = []
    sub = lambda s, m: (dt.datetime.fromisoformat(s) + dt.timedelta(minutes=m)).isoformat(timespec="seconds")
    for d in deliveries:
        pd = dt.date.fromisoformat(d["planned_date"])
        ev.append(("DELIVERY", d["delivery_id"], 1, None, "CREATED", odate[d["order_id"]] + "T09:00:00", "SYSTEM"))
        sched = ts(pd - dt.timedelta(days=1), 18 * 60 + 5)
        if d["assignment_status"] == "UNSERVED":
            ev.append(("DELIVERY", d["delivery_id"], 2, "CREATED", "UNSERVED", sched, "PLANNER"))
            continue
        r = rmap[d["assigned_route_id"]]
        o = omap[d["delivery_id"]]
        disp = sub(r["actual_departure"], -10)
        fin = o["actual_departure"] or r["actual_return"]
        ev += [("DELIVERY", d["delivery_id"], 2, "CREATED", "SCHEDULED", sched, "PLANNER"),
               ("DELIVERY", d["delivery_id"], 3, "SCHEDULED", "DISPATCHED", disp, "CARRIER_OPERATOR"),
               ("DELIVERY", d["delivery_id"], 4, "DISPATCHED", o["outcome_status"], fin, "DRIVER")]
    for r in routes:
        pd = dt.date.fromisoformat(r["route_date"])
        ev += [("ROUTE", r["route_id"], 1, None, "PLANNED", ts(pd - dt.timedelta(days=1), 18 * 60 + 5), "PLANNER"),
               ("ROUTE", r["route_id"], 2, "PLANNED", "DISPATCHED", sub(r["actual_departure"], -10), "CARRIER_OPERATOR"),
               ("ROUTE", r["route_id"], 3, "DISPATCHED", "IN_PROGRESS", r["actual_departure"], "DRIVER"),
               ("ROUTE", r["route_id"], 4, "IN_PROGRESS", "COMPLETED", r["actual_return"], "DRIVER")]
    ev.sort(key=lambda e: (e[5], e[0], e[1], e[2]))
    return [dict(event_id=f"EVT-{i:07d}", entity_type=e[0], entity_id=e[1], event_seq=e[2], from_status=e[3],
                 to_status=e[4], event_ts=e[5], actor_role=e[6]) for i, e in enumerate(ev, 1)]


# ------------------------------------------------------------------ labelled anomaly injection
def inject(T, cfg):
    r = R(cfg, "anomaly")
    n = cfg["anomalies"]
    gt, used = [], set()
    routes = sorted(T["route"], key=lambda x: x["route_id"])
    stops_by, outs_by = defaultdict(list), defaultdict(list)
    for s in T["route_stop"]:
        stops_by[s["route_id"]].append(s)
    for o in T["delivery_outcome"]:
        outs_by[o["route_id"]].append(o)
    for v in list(stops_by.values()) + list(outs_by.values()):
        v.sort(key=lambda x: x.get("stop_sequence") or x["stop_id"])
    dm = {d["delivery_id"]: d for d in T["delivery"]}
    om = {o["order_id"]: o for o in T["order"]}
    sm = {s["shift_id"]: s for s in T["shift"]}
    ostop = {o["stop_id"]: o for o in T["delivery_outcome"]}

    def add(itype, etype, eid, rid, related, field, orig, new, rule):
        gt.append(dict(anomaly_id=f"GT-{len(gt) + 1:04d}", issue_type=itype, entity_type=etype, entity_id=eid,
                       route_id=rid, related_ids=";".join(related), field=field, original_value=orig,
                       injected_value=new, detection_rule=rule))

    def pick(pred):
        c = [x for x in routes if x["route_id"] not in used and pred(x)]
        r.shuffle(c)
        out = c[:n]
        used.update(x["route_id"] for x in out)
        return out

    # A: route exceeds capacity (raise one delivery's demand, keep all derived totals consistent)
    for rt in pick(lambda x: x["stop_count"] >= 2):
        st = stops_by[rt["route_id"]]
        d = dm[r.choice(st)["delivery_id"]]
        total, cap = rt["planned_load_kg"], rt["capacity_kg_at_plan"]
        old = d["demand_kg"]
        new = round(cap * r.uniform(1.08, 1.25) - (total - old), 1)
        ratio = new / old
        for obj in (d, om[d["order_id"]]):
            obj["demand_kg"] = new; obj["demand_volume_m3"] = round(obj["demand_volume_m3"] * ratio, 3)
        rt["planned_load_kg"] = round(total - old + new, 1)
        rt["planned_load_m3"] = round(sum(dm[s["delivery_id"]]["demand_volume_m3"] for s in st), 3)
        rt["load_utilization_pct"] = round(rt["planned_load_kg"] / cap * 100, 2)
        rem = rt["planned_load_kg"]
        for s in st:
            rem = round(rem - dm[s["delivery_id"]]["demand_kg"], 1); s["load_after_stop_kg"] = rem
        add("ROUTE_EXCEEDS_CAPACITY", "ROUTE", rt["route_id"], rt["route_id"], [d["delivery_id"]], "delivery.demand_kg",
            old, new, "planned_load_kg > capacity_kg_at_plan")
    # B: stop omitted (stop + outcome rows removed; delivery still assigned to the route)
    drop_stop, drop_out = set(), set()
    for rt in pick(lambda x: x["stop_count"] >= 3):
        s = r.choice(stops_by[rt["route_id"]])
        drop_stop.add(s["stop_id"]); drop_out.add(ostop[s["stop_id"]]["outcome_id"])
        add("STOP_OMITTED", "ROUTE", rt["route_id"], rt["route_id"], [s["stop_id"], s["delivery_id"]], "route_stop",
            "present", "row removed", "delivery.assigned_route_id has no route_stop / COUNT(route_stop) < stop_count")
    T["route_stop"] = [s for s in T["route_stop"] if s["stop_id"] not in drop_stop]
    T["delivery_outcome"] = [o for o in T["delivery_outcome"] if o["outcome_id"] not in drop_out]
    # C: stop duplicated
    for rt in pick(lambda x: x["stop_count"] >= 2):
        st = stops_by[rt["route_id"]]
        s, last = r.choice(st), st[-1]
        k = len(st) + 1
        dup = dict(s, stop_id=f"STOP-{rt['route_id']}-{k:03d}", stop_sequence=k, planned_arrival=last["planned_departure"],
                   planned_service_start=last["planned_departure"],
                   planned_departure=(dt.datetime.fromisoformat(last["planned_departure"]) +
                                      dt.timedelta(minutes=s["service_minutes"])).isoformat(timespec="seconds"),
                   leg_distance_km=0.0, leg_travel_minutes=0.0)
        T["route_stop"].append(dup)
        add("STOP_DUPLICATED", "ROUTE", rt["route_id"], rt["route_id"], [dup["stop_id"], s["stop_id"], s["delivery_id"]],
            "route_stop", "1 stop", "2 stops same delivery", "delivery_id occurs >1 time in route_stop / rows > stop_count")
    # D: arrival before previous departure
    def okD(x):
        o = [q for q in outs_by[x["route_id"]] if q["actual_arrival"]]
        return len(o) >= 2
    for rt in pick(okD):
        o = [q for q in outs_by[rt["route_id"]] if q["actual_arrival"]]
        k = r.randint(1, len(o) - 1)
        prev, cur = o[k - 1], o[k]
        new = (dt.datetime.fromisoformat(prev["actual_departure"]) - dt.timedelta(minutes=r.uniform(5, 25))).isoformat(timespec="seconds")
        old = cur["actual_arrival"]
        pa = next(s for s in T["route_stop"] if s["stop_id"] == cur["stop_id"])["planned_arrival"]
        cur["actual_arrival"] = new
        cur["delay_minutes"] = round((dt.datetime.fromisoformat(new) - dt.datetime.fromisoformat(pa)).total_seconds() / 60, 2)
        add("ARRIVAL_BEFORE_PREV_DEPARTURE", "DELIVERY_OUTCOME", cur["outcome_id"], rt["route_id"], [prev["outcome_id"]],
            "actual_arrival", old, new, "actual_arrival < previous stop actual_departure")
    # E: driver shift exceeded
    for rt in pick(lambda x: True):
        end = dt.datetime.fromisoformat(sm[rt["shift_id"]]["shift_end"])
        new = (end + dt.timedelta(minutes=r.uniform(10, 60))).isoformat(timespec="seconds")
        old = rt["actual_return"]
        rt["actual_return"] = new
        add("DRIVER_SHIFT_EXCEEDED", "ROUTE", rt["route_id"], rt["route_id"], [rt["shift_id"]], "route.actual_return",
            old, new, "route.actual_return > shift.shift_end")
    # F: coordinate outside region
    cs = sorted((s for s in T["customer_site"] if s["site_type"] == "CUSTOMER"), key=lambda s: s["site_id"])
    for s in r.sample(cs, min(n, len(cs))):
        old = f"{s['latitude']},{s['longitude']}"
        s["latitude"] = round(r.choice([r.uniform(19.0, 28.9), r.uniform(8.0, 15.5)]), 6)
        s["longitude"] = round(r.uniform(72.0, 88.0), 6)
        add("COORDINATE_OUTSIDE_REGION", "CUSTOMER_SITE", s["site_id"], "", [], "latitude,longitude", old,
            f"{s['latitude']},{s['longitude']}", "lat/lon outside BBOX 17.20..17.60 / 78.25..78.65")
    return gt


def decision_labels(T):
    """Expected-decision labels per delivery (kept out of input tables)."""
    om = {o["delivery_id"]: o for o in T["delivery_outcome"]}
    rows = []
    for d in T["delivery"]:
        o = om.get(d["delivery_id"])
        rows.append(dict(delivery_id=d["delivery_id"], expected_decision=d["assignment_status"],
                         expected_unserved_reason=d["unserved_reason_code"] or "",
                         expected_outcome=d["delivery_status"], expected_failure_reason=(o["reason_code"] if o and o["reason_code"] else ""),
                         rule_ref="README#outcome-rules"))
    return rows


# ------------------------------------------------------------------ export
def fmt(v):
    return "" if v is None else v


def write_csv(path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow([fmt(r.get(c)) for c in cols])


def sql_lit(v, typ):
    if v is None or v == "":
        return "NULL"
    if typ in ("int", "float"):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def qt(name):
    return '"order"' if name == "order" else name


def ddl():
    out = ["PRAGMA foreign_keys = ON;"]
    for name in schema.TABLE_ORDER:
        sp = schema.T[name]
        cols = [f"  {f['name']} {schema.SQL_TYPES[f['type']]}{' NOT NULL' if f['required'] else ''}" for f in sp["fields"]]
        cols.append(f"  PRIMARY KEY ({', '.join(sp['pk'])})")
        for c, (pt, pc) in sp["fks"].items():
            cols.append(f"  FOREIGN KEY ({c}) REFERENCES {qt(pt)}({pc})")
        out.append(f"CREATE TABLE {qt(name)} (\n" + ",\n".join(cols) + "\n);")
    return "\n".join(out) + "\n"


def write_sql(path, T):
    # parents before children; route<->delivery circular FK is satisfied by inserting delivery before route with FKs deferred
    with open(path, "w", encoding="utf-8") as f:
        f.write("PRAGMA foreign_keys = OFF;\nBEGIN;\n")
        for name in schema.TABLE_ORDER:
            q = qt(name)
            sp = schema.T[name]
            cols = schema.columns(name)
            types = {x["name"]: x["type"] for x in sp["fields"]}
            rows = T[name]
            for i in range(0, len(rows), 500):
                vals = ",\n".join("(" + ",".join(sql_lit(r.get(c), types[c]) for c in cols) + ")" for r in rows[i:i + 500])
                f.write(f"INSERT INTO {q} ({','.join(cols)}) VALUES\n{vals};\n")
        f.write("COMMIT;\nPRAGMA foreign_keys = ON;\n")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def write_dictionary(outdir):
    rows, md = [], ["# Data Dictionary\n", "Generated from `schema.py` (single source of truth). Times are local-naive ISO-8601; "
                    "units as stated. `req` = required. IDs are immutable and zero-padded.\n"]
    for name in schema.TABLE_ORDER:
        sp = schema.T[name]
        md.append(f"\n## {sp['entity']} — `{name}`\n\n{sp['description']}\n")
        md.append(f"- **Primary key:** {', '.join(sp['pk'])}")
        md.append("- **Foreign keys:** " + (", ".join(f"{c} -> {t}.{k}" for c, (t, k) in sp["fks"].items()) or "none"))
        md.append("- **Cardinality:** " + "; ".join(sp["cardinality"]) + "\n")
        md.append("| field | type | req | allowed values | unit | unique | validation rule |\n|---|---|---|---|---|---|---|")
        for f in sp["fields"]:
            md.append(f"| {f['name']} | {f['type']} | {'Y' if f['required'] else 'N'} | {f['allowed']} | {f['unit']} | "
                      f"{'Y' if f['unique'] or f['name'] in sp['pk'] and len(sp['pk']) == 1 else 'N'} | "
                      f"{(f['pattern'] + '; ' if f['pattern'] else '')}{f['rule']} |".replace("|  |", "| |"))
            rows.append(dict(table=name, entity=sp["entity"], field=f["name"], type=f["type"], required=f["required"],
                             allowed=f["allowed"], unit=f["unit"], unique=f["unique"], pattern=f["pattern"] or "", rule=f["rule"]))
    md.append("\n## Lifecycle states\n\n- Delivery: CREATED -> SCHEDULED -> DISPATCHED -> DELIVERED | FAILED; CREATED -> UNSERVED\n"
              "- Route: PLANNED -> DISPATCHED -> IN_PROGRESS -> COMPLETED\n- History is append-only in `status_event`; "
              "`*_status` columns on parent tables are terminal snapshots.\n")
    with open(os.path.join(outdir, "docs", "data_dictionary.md"), "w") as f:
        f.write("\n".join(md))
    write_csv(os.path.join(outdir, "docs", "data_dictionary.csv"), list(rows[0].keys()), rows)


def export(T, final_T, gt, labels, cfg, outdir, summary, command):
    for sub in ("csv", "json", "sql", "baseline_csv", "docs"):
        os.makedirs(os.path.join(outdir, sub), exist_ok=True)
    for name in schema.TABLE_ORDER:
        write_csv(os.path.join(outdir, "csv", f"{name}.csv"), schema.columns(name), final_T[name])
        if name != "travel_time_matrix":
            with open(os.path.join(outdir, "json", f"{name}.json"), "w") as f:
                json.dump([{c: r.get(c) for c in schema.columns(name)} for r in final_T[name]], f, indent=1)
        if final_T[name] is not T[name]:
            write_csv(os.path.join(outdir, "baseline_csv", f"{name}.csv"), schema.columns(name), T[name])
    with open(os.path.join(outdir, "sql", "schema.sql"), "w") as f:
        f.write(ddl())
    write_sql(os.path.join(outdir, "sql", "seed.sql"), final_T)
    gcols = ["anomaly_id", "issue_type", "entity_type", "entity_id", "route_id", "related_ids", "field",
             "original_value", "injected_value", "detection_rule"]
    gdir = os.path.join(outdir, "ground_truth")
    os.makedirs(gdir, exist_ok=True)
    write_csv(os.path.join(gdir, "ground_truth.csv"), gcols, gt)
    with open(os.path.join(gdir, "ground_truth.json"), "w") as f:
        json.dump(gt, f, indent=1)
    write_csv(os.path.join(gdir, "ground_truth_labels.csv"), list(labels[0].keys()), labels)
    write_dictionary(outdir)
    src = dict(external_data_used=False, sources=[],
               statement="All records are synthetic, generated from a fixed seed. No external datasets, scraped data, or personal data were used.",
               schema_inspiration="Public VRPTW benchmark conventions (Solomon-style time windows, capacities); no data copied.",
               region="Bounding box 17.20..17.60 N, 78.25..78.65 E (Hyderabad metro envelope) used only as a coordinate frame for synthetic points.",
               transformations="n/a", fields_discarded="n/a")
    with open(os.path.join(outdir, "docs", "source_manifest.json"), "w") as f:
        json.dump(src, f, indent=2)
    with open(os.path.join(outdir, "docs", "validation_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    files = {}
    for sub in ("csv", "baseline_csv", "ground_truth"):
        for fn in sorted(os.listdir(os.path.join(outdir, sub))):
            files[f"{sub}/{fn}"] = sha256(os.path.join(outdir, sub, fn))
    man = dict(generator="generator.py", command=command, seed=cfg["seed"], scale=cfg["scale"], parameters={
        k: cfg[k] for k in ("sites", "deliveries", "vehicles", "drivers", "days", "anomalies")},
        start_date=START.isoformat(), row_counts={n: len(final_T[n]) for n in schema.TABLE_ORDER},
        baseline_row_counts={n: len(T[n]) for n in schema.TABLE_ORDER}, sha256=files)
    with open(os.path.join(outdir, "docs", "dataset_manifest.json"), "w") as f:
        json.dump(man, f, indent=2)
    return man


def make_cfg(args):
    base = dict(SCALES[args.scale])
    for k in ("sites", "deliveries", "vehicles", "days"):
        if getattr(args, k) is not None:
            base[k] = getattr(args, k)
    base.update(seed=args.seed, scale=args.scale, drivers=math.ceil(base["vehicles"] * 1.2),
                anomalies=args.anomalies if args.anomalies is not None else max(2, round(base["deliveries"] / 250)))
    return base


def run(cfg, outdir, command=""):
    T = build(cfg)
    base_issues, base_checks = validate.run_all(T, cfg["seed"])
    final_T = dict(T)
    for k in ("customer_site", "order", "delivery", "route", "route_stop", "delivery_outcome"):
        final_T[k] = copy.deepcopy(T[k])
    gt = inject(final_T, cfg)
    labels = decision_labels(T)
    fin_issues, fin_checks = validate.run_all(final_T, cfg["seed"])
    ev = validate.evaluate(fin_issues, gt)
    summary = dict(
        baseline=dict(violations=len(base_issues), checks=base_checks,
                      status="PASS" if not base_issues else "FAIL"),
        final_with_injected_anomalies=dict(checks=fin_checks, detection=ev),
        reproducibility="see docs/reproducibility_report.json (python repro_check.py)")
    man = export(T, final_T, gt, labels, cfg, outdir, summary, command)
    return T, final_T, gt, summary, man


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=20261022)
    ap.add_argument("--scale", choices=SCALES, default="full")
    ap.add_argument("--out", default=None)
    for k in ("sites", "deliveries", "vehicles", "days", "anomalies"):
        ap.add_argument(f"--{k}", type=int, default=None, help=f"override scale preset ({k})")
    args = ap.parse_args(argv)
    cfg = make_cfg(args)
    out = args.out or os.path.join("data", args.scale)
    cmd = "python generator.py " + " ".join(shlex.quote(a) for a in (argv if argv is not None else sys.argv[1:]))
    T, final_T, gt, summary, man = run(cfg, out, cmd)
    b = summary["baseline"]; d = summary["final_with_injected_anomalies"]["detection"]
    print(f"[{cfg['scale']}] seed={cfg['seed']} rows=" + ", ".join(f"{k}={v}" for k, v in man["row_counts"].items()))
    print(f"baseline validation: {b['status']} ({b['violations']} violations)")
    print(f"anomalies injected={len(gt)} detected TP={d['tp']} FP={d['fp']} FN={d['fn']} "
          f"precision={d['precision']} recall={d['recall']} collateral_findings={d['collateral_findings']}")
    return 0 if not b["violations"] and d["fn"] == 0 and d["fp"] == 0 and d["collateral_findings"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
