#!/usr/bin/env python3
"""Validation: PK uniqueness, FK integrity, enums, date ordering, arithmetic reconciliation, lifecycle,
duplicates, business constraints, acceptance criteria.  Works on in-memory rows or a CSV directory.

  python validate.py data/full/csv [--ground-truth data/full/ground_truth/ground_truth.csv]
"""
import argparse, csv, datetime as dt, json, os, re, sys
from collections import defaultdict

import schema
from common import *

INJECTABLE = {"ROUTE_EXCEEDS_CAPACITY", "STOP_OMITTED", "STOP_DUPLICATED", "ARRIVAL_BEFORE_PREV_DEPARTURE",
              "DRIVER_SHIFT_EXCEEDED", "COORDINATE_OUTSIDE_REGION"}
P = dt.datetime.fromisoformat
TOL_MIN, TOL_KM = 0.06, 0.003


def mins(a, b):
    return (P(b) - P(a)).total_seconds() / 60.0


def clock(s):
    x = P(s)
    return x.hour * 60 + x.minute + x.second / 60.0


def hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def load_dir(path):
    T = {}
    for name in schema.TABLE_ORDER:
        types = {f["name"]: f["type"] for f in schema.T[name]["fields"]}
        rows = []
        with open(os.path.join(path, f"{name}.csv"), newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                row = {}
                for k, v in r.items():
                    if v == "":
                        row[k] = None
                    elif types[k] == "int":
                        row[k] = int(v)
                    elif types[k] == "float":
                        row[k] = float(v)
                    else:
                        row[k] = v
                rows.append(row)
        T[name] = rows
    return T


def run_all(T, seed):
    issues = []

    def add(check, itype, etype, eid, detail=""):
        issues.append(dict(check=check, issue_type=itype, entity_type=etype, entity_id=str(eid), detail=detail))

    checks = {}
    pk = {n: {tuple(r[c] for c in schema.T[n]["pk"]) for r in T[n]} for n in schema.T}

    # 1. primary keys / uniqueness / patterns / required / enums
    for n, sp in schema.T.items():
        seen = set()
        for r in T[n]:
            k = tuple(r[c] for c in sp["pk"])
            if k in seen:
                add("PK_UNIQUE", "PK_DUPLICATE", n, k)
            seen.add(k)
        for f in sp["fields"]:
            vals = set()
            ev = schema.enum_values(f)
            for r in T[n]:
                v = r.get(f["name"])
                key = r[sp["pk"][0]]
                if v is None:
                    if f["required"]:
                        add("REQUIRED", "REQUIRED_MISSING", n, key, f["name"])
                    continue
                if ev and str(v) not in ev:
                    add("ENUM", "ENUM_INVALID", n, key, f"{f['name']}={v}")
                if f["pattern"] and not re.fullmatch(f["pattern"], str(v)):
                    add("ID_FORMAT", "ID_FORMAT_INVALID", n, key, f"{f['name']}={v}")
                if f["unique"]:
                    if v in vals:
                        add("UNIQUE", "UNIQUE_DUPLICATE", n, key, f["name"])
                    vals.add(v)
    checks["pk_uniqueness_required_enum_idformat"] = _count(issues, ("PK_DUPLICATE", "REQUIRED_MISSING", "ENUM_INVALID", "ID_FORMAT_INVALID", "UNIQUE_DUPLICATE"))

    # 2. foreign keys
    for n, sp in schema.T.items():
        for col, (pt, pc) in sp["fks"].items():
            ref = {k[0] for k in pk[pt]}
            for r in T[n]:
                if r[col] is not None and r[col] not in ref:
                    add("FK", "FK_BROKEN", n, r[sp["pk"][0]], f"{col}->{pt}.{pc}={r[col]}")
    ref_ent = {"DELIVERY": {k[0] for k in pk["delivery"]}, "ROUTE": {k[0] for k in pk["route"]}}
    for e in T["status_event"]:
        if e["entity_id"] not in ref_ent[e["entity_type"]]:
            add("FK", "FK_BROKEN", "status_event", e["event_id"], "entity_id")
    checks["foreign_keys"] = _count(issues, ("FK_BROKEN",))

    S = {s["site_id"]: s for s in T["customer_site"]}
    V = {v["vehicle_id"]: v for v in T["vehicle"]}
    D = {d["driver_id"]: d for d in T["driver"]}
    SH = {s["shift_id"]: s for s in T["shift"]}
    RT = {r["route_id"]: r for r in T["route"]}
    DL = {d["delivery_id"]: d for d in T["delivery"]}
    OR = {o["order_id"]: o for o in T["order"]}
    TW = {t["delivery_id"]: t for t in T["time_window"]}
    CAP = {c["capacity_id"]: c for c in T["vehicle_capacity"]}
    stops_by, outs_by, stop_ids = defaultdict(list), defaultdict(list), {}
    for s in T["route_stop"]:
        stops_by[s["route_id"]].append(s); stop_ids[s["stop_id"]] = s
    for o in T["delivery_outcome"]:
        outs_by[o["route_id"]].append(o)
    for v in stops_by.values():
        v.sort(key=lambda x: x["stop_sequence"])
    seqmap = {}
    for rid, v in outs_by.items():
        v.sort(key=lambda x: stop_ids[x["stop_id"]]["stop_sequence"] if x["stop_id"] in stop_ids else 10 ** 6)
    assigned_by = defaultdict(list)
    for d in T["delivery"]:
        if d["assigned_route_id"]:
            assigned_by[d["assigned_route_id"]].append(d)

    # 3. injected-type detections ------------------------------------------------
    bad_sites = set()
    for s in T["customer_site"]:
        if s["site_type"] == "CUSTOMER" and not (BBOX["lat_min"] <= s["latitude"] <= BBOX["lat_max"]
                                                  and BBOX["lon_min"] <= s["longitude"] <= BBOX["lon_max"]):
            add("REGION", "COORDINATE_OUTSIDE_REGION", "CUSTOMER_SITE", s["site_id"]); bad_sites.add(s["site_id"])
    structural = set()
    for rid, r in RT.items():
        st = stops_by[rid]
        ids = [s["delivery_id"] for s in st]
        seqs = [s["stop_sequence"] for s in st]
        omitted = (len(st) < r["stop_count"]) or any(d["delivery_id"] not in ids for d in assigned_by[rid]) \
            or (sorted(set(seqs)) != list(range(1, len(set(seqs)) + 1)))
        dup = len(ids) != len(set(ids)) or len(st) > r["stop_count"]
        if omitted:
            add("STOP_COVERAGE", "STOP_OMITTED", "ROUTE", rid); structural.add(rid)
        if dup:
            add("STOP_COVERAGE", "STOP_DUPLICATED", "ROUTE", rid); structural.add(rid)
    for did, d in DL.items():
        pass
    cap_ok = set()
    for rid, r in RT.items():
        if r["planned_load_kg"] > r["capacity_kg_at_plan"] + 1e-6 or r["planned_load_m3"] > r["capacity_m3_at_plan"] + 1e-6:
            add("CAPACITY", "ROUTE_EXCEEDS_CAPACITY", "ROUTE", rid, f"{r['planned_load_kg']}>{r['capacity_kg_at_plan']}")
        sh = SH.get(r["shift_id"])
        if sh and (P(r["actual_return"]) > P(sh["shift_end"]) or P(r["actual_departure"]) < P(sh["shift_start"])):
            add("SHIFT", "DRIVER_SHIFT_EXCEEDED", "ROUTE", rid, f"{r['actual_return']}>{sh['shift_end']}")
    for rid, outs in outs_by.items():
        prev = None
        for o in outs:
            if o["actual_arrival"] is None:
                continue
            if prev is not None and P(o["actual_arrival"]) < P(prev) - dt.timedelta(seconds=1):
                add("SEQUENCE_TIME", "ARRIVAL_BEFORE_PREV_DEPARTURE", "DELIVERY_OUTCOME", o["outcome_id"])
            prev = o["actual_departure"]
    for rid in structural:
        pass
    checks["injectable_anomaly_rules"] = _count(issues, INJECTABLE)

    # 4. date ordering ---------------------------------------------------------
    n0 = len(issues)
    for o in T["order"]:
        d = DL.get(next((x["delivery_id"] for x in T["delivery"] if False), None)) if False else None
    dby_order = {d["order_id"]: d for d in T["delivery"]}
    for o in T["order"]:
        if not o["order_date"] < o["requested_date"]:
            add("DATE_ORDER", "DATE_ORDER", "order", o["order_id"])
        d = dby_order.get(o["order_id"])
        if d and d["planned_date"] != o["requested_date"]:
            add("DATE_ORDER", "DATE_ORDER", "order", o["order_id"], "requested_date != planned_date")
    for t in T["time_window"]:
        d, s = DL.get(t["delivery_id"]), None
        if d:
            s = S[d["site_id"]]
            if not P(t["window_start"]) < P(t["window_end"]) or t["window_start"][:10] != d["planned_date"]:
                add("DATE_ORDER", "DATE_ORDER", "time_window", t["tw_id"])
            if clock(t["window_start"]) < hm(s["open_time"]) or clock(t["window_end"]) > hm(s["close_time"]):
                add("DATE_ORDER", "WINDOW_OUTSIDE_SITE_HOURS", "time_window", t["tw_id"])
    for s in T["shift"]:
        if not P(s["shift_start"]) < P(s["shift_end"]) or s["shift_start"][:10] != s["shift_date"]:
            add("DATE_ORDER", "DATE_ORDER", "shift", s["shift_id"])
        if s["max_duty_minutes"] != round(mins(s["shift_start"], s["shift_end"])) - s["break_minutes"]:
            add("RECON", "RECON_MISMATCH", "shift", s["shift_id"], "max_duty_minutes")
    for c in T["vehicle_capacity"]:
        if c["effective_to"] and c["effective_to"] < c["effective_from"]:
            add("DATE_ORDER", "DATE_ORDER", "vehicle_capacity", c["capacity_id"])
    vc = defaultdict(list)
    for c in T["vehicle_capacity"]:
        vc[c["vehicle_id"]].append(c)
    for vid, cs in vc.items():
        cs.sort(key=lambda c: c["version"])
        for a, b in zip(cs, cs[1:]):
            if a["effective_to"] is None or a["effective_to"] >= b["effective_from"]:
                add("DATE_ORDER", "CAPACITY_VERSION_OVERLAP", "vehicle_capacity", b["capacity_id"])
    for rid, r in RT.items():
        if not P(r["planned_departure"]) < P(r["planned_return"]) or P(r["actual_return"]) < P(r["actual_departure"]):
            add("DATE_ORDER", "DATE_ORDER", "route", rid)
        for s in stops_by[rid]:
            if not (P(s["planned_arrival"]) <= P(s["planned_service_start"]) <= P(s["planned_departure"])):
                add("DATE_ORDER", "DATE_ORDER", "route_stop", s["stop_id"])
    for o in T["delivery_outcome"]:
        a, b, c = o["actual_arrival"], o["actual_service_start"], o["actual_departure"]
        if a and c and not P(a) <= P(c):
            add("DATE_ORDER", "DATE_ORDER", "delivery_outcome", o["outcome_id"])
        if a and b and not P(a) <= P(b) <= P(c):
            add("DATE_ORDER", "DATE_ORDER", "delivery_outcome", o["outcome_id"])
    checks["date_ordering"] = len(issues) - n0

    # 5. arithmetic reconciliation / matrix reproducibility ---------------------
    n0 = len(issues)
    for d in T["delivery"]:
        o = OR.get(d["order_id"])
        if o and (o["demand_kg"] != d["demand_kg"] or o["demand_volume_m3"] != d["demand_volume_m3"]
                  or o["site_id"] != d["site_id"] or o["priority"] != d["priority"]):
            add("RECON", "RECON_MISMATCH", "delivery", d["delivery_id"], "order/delivery copy fields")
    M = {}
    ll = {s["site_id"]: (s["latitude"], s["longitude"]) for s in T["customer_site"]}
    for m in T["travel_time_matrix"]:
        M[(m["matrix_date"], m["from_site_id"], m["to_site_id"])] = m
        if abs(m["base_minutes"] - base_minutes(m["distance_km"])) > 0.011:
            add("MATRIX", "MATRIX_MISMATCH", "travel_time_matrix", f"{m['matrix_date']}|{m['from_site_id']}|{m['to_site_id']}", "base")
        for i, b in enumerate(BANDS):
            if abs(m[f"minutes_{b}"] - band_minutes(m["base_minutes"], m["scenario_multiplier"], i)) > 0.011:
                add("MATRIX", "MATRIX_MISMATCH", "travel_time_matrix", f"{m['matrix_date']}|{m['from_site_id']}|{m['to_site_id']}", b)
        a, b2 = m["from_site_id"], m["to_site_id"]
        if a not in bad_sites and b2 not in bad_sites and a in ll and b2 in ll:
            if abs(m["distance_km"] - road_km(seed, a, ll[a], b2, ll[b2])) > 0.0011:
                add("MATRIX", "MATRIX_MISMATCH", "travel_time_matrix", f"{m['matrix_date']}|{a}|{b2}", "distance not reproducible")
    for rid, r in RT.items():
        if rid in structural:
            continue
        st = stops_by[rid]
        load = round(sum(d["demand_kg"] for d in assigned_by[rid]), 1)
        if abs(load - r["planned_load_kg"]) > 0.05 or abs(sum(d["demand_volume_m3"] for d in assigned_by[rid]) - r["planned_load_m3"]) > 0.002:
            add("RECON", "RECON_MISMATCH", "route", rid, "planned load")
        if r["stop_count"] != len(st) or r["delivered_count"] + r["failed_count"] != len(st):
            add("RECON", "RECON_MISMATCH", "route", rid, "counts")
        if abs(r["load_utilization_pct"] - round(r["planned_load_kg"] / r["capacity_kg_at_plan"] * 100, 2)) > 0.011:
            add("RECON", "RECON_MISMATCH", "route", rid, "utilization")
        cp = CAP.get(r["vehicle_capacity_id"])
        if cp and (cp["vehicle_id"] != r["vehicle_id"] or cp["max_weight_kg"] != r["capacity_kg_at_plan"]
                   or not (cp["effective_from"] <= r["route_date"] and (cp["effective_to"] is None or r["route_date"] <= cp["effective_to"]))):
            add("RECON", "RECON_MISMATCH", "route", rid, "capacity version")
        # planned chain: distances/times reproducible from the matrix
        prev, tprev, dist, drive = DEPOT_ID, r["planned_departure"], 0.0, 0.0
        for s in st:
            m = M.get((r["route_date"], prev, s["site_id"]))
            if m is None:
                add("MATRIX", "MATRIX_MISSING", "route_stop", s["stop_id"]); break
            legm = m[f"minutes_{BANDS[band_index(clock(tprev))]}"]
            tw = TW[s["delivery_id"]]
            ok = (abs(m["distance_km"] - s["leg_distance_km"]) <= TOL_KM and abs(legm - s["leg_travel_minutes"]) <= 0.011
                  and abs(mins(tprev, s["planned_arrival"]) - legm) <= TOL_MIN
                  and abs(mins(max(s["planned_arrival"], tw["window_start"]), s["planned_service_start"])) <= TOL_MIN
                  and abs(mins(s["planned_service_start"], s["planned_departure"]) - s["service_minutes"]) <= TOL_MIN
                  and P(s["planned_arrival"]) >= P(tprev))
            if not ok:
                add("RECON", "RECON_MISMATCH", "route_stop", s["stop_id"], "planned chain")
            dist += s["leg_distance_km"]; drive += s["leg_travel_minutes"]; prev, tprev = s["site_id"], s["planned_departure"]
        else:
            m = M.get((r["route_date"], prev, DEPOT_ID))
            if m and (abs(dist + r["return_leg_km"] - r["planned_distance_km"]) > TOL_KM * 2
                      or abs(drive + r["return_leg_minutes"] - r["planned_drive_minutes"]) > 0.02
                      or abs(m["distance_km"] - r["return_leg_km"]) > TOL_KM
                      or abs(mins(tprev, r["planned_return"]) - r["return_leg_minutes"]) > TOL_MIN):
                add("RECON", "RECON_MISMATCH", "route", rid, "distance/time totals")
        ostop = {o["stop_id"]: o for o in outs_by[rid]}
        nd = nf = 0
        for s in st:
            o = ostop.get(s["stop_id"])
            if o is None:
                add("RECON", "RECON_MISMATCH", "route_stop", s["stop_id"], "no outcome"); continue
            nd += o["outcome_status"] == "DELIVERED"; nf += o["outcome_status"] == "FAILED"
            if o["actual_arrival"] and o["delay_minutes"] is not None and abs(o["delay_minutes"] - mins(s["planned_arrival"], o["actual_arrival"])) > 0.03:
                add("RECON", "RECON_MISMATCH", "delivery_outcome", o["outcome_id"], "delay_minutes")
        if (nd, nf) != (r["delivered_count"], r["failed_count"]):
            add("RECON", "RECON_MISMATCH", "route", rid, "outcome counts")
    checks["arithmetic_reconciliation_and_matrix_reproducibility"] = len(issues) - n0

    # 6. business constraints --------------------------------------------------
    n0 = len(issues)
    booked = set()
    for s in T["shift"]:
        for k in (("d", s["driver_id"], s["shift_date"]), ("v", s["vehicle_id"], s["shift_date"])):
            if k in booked:
                add("CONSTRAINT", "DOUBLE_BOOKING", "shift", s["shift_id"], str(k))
            booked.add(k)
        if D[s["driver_id"]]["max_vehicle_class_rank"] < V[s["vehicle_id"]]["class_rank"]:
            add("CONSTRAINT", "DRIVER_NOT_QUALIFIED", "shift", s["shift_id"])
        if V[s["vehicle_id"]]["status"] != "ACTIVE":
            add("CONSTRAINT", "VEHICLE_NOT_ACTIVE", "shift", s["shift_id"])
    for rid, r in RT.items():
        sh = SH.get(r["shift_id"])
        if sh and (sh["vehicle_id"] != r["vehicle_id"] or sh["driver_id"] != r["driver_id"] or sh["shift_date"] != r["route_date"]):
            add("CONSTRAINT", "ROUTE_SHIFT_MISMATCH", "route", rid)
        if sh and (P(r["planned_departure"]) < P(sh["shift_start"]) or P(r["planned_return"]) > P(sh["shift_end"])):
            add("CONSTRAINT", "PLAN_OUTSIDE_SHIFT", "route", rid)
        cp = CAP.get(r["vehicle_capacity_id"])
        if cp and len(stops_by[rid]) > cp["max_stops"] and rid not in structural:
            add("CONSTRAINT", "MAX_STOPS_EXCEEDED", "route", rid)
        for s in stops_by[rid]:
            if V[r["vehicle_id"]]["class_rank"] > S[s["site_id"]]["max_vehicle_class_rank"]:
                add("CONSTRAINT", "RESTRICTED_VEHICLE", "route_stop", s["stop_id"])
            tw = TW.get(s["delivery_id"])
            if tw:
                late = mins(tw["window_end"], s["planned_arrival"])
                if late > (0 if tw["window_type"] == "HARD" else tw["grace_minutes"]) + 1e-6 and s["stop_sequence"] <= r["stop_count"]:
                    add("CONSTRAINT", "PLANNED_WINDOW_VIOLATION", "route_stop", s["stop_id"])
    checks["business_constraints"] = len(issues) - n0

    # 7. acceptance criteria & lifecycle --------------------------------------
    n0 = len(issues)
    ost = {o["delivery_id"]: o for o in T["delivery_outcome"]}
    for d in T["delivery"]:
        if d["assignment_status"] == "ASSIGNED":
            if not d["assigned_route_id"] or d["unserved_reason_code"]:
                add("ACCEPT", "ASSIGNMENT_INCONSISTENT", "delivery", d["delivery_id"])
        elif d["assigned_route_id"] or not d["unserved_reason_code"] or d["delivery_status"] != "UNSERVED":
            add("ACCEPT", "UNSERVED_WITHOUT_REASON", "delivery", d["delivery_id"])
        o = ost.get(d["delivery_id"])
        if d["assigned_route_id"] not in structural and d["assignment_status"] == "ASSIGNED":
            if o is None or o["outcome_status"] != d["delivery_status"]:
                add("LIFECYCLE", "STATUS_OUTCOME_MISMATCH", "delivery", d["delivery_id"])
        if OR.get(d["order_id"]) and OR[d["order_id"]]["order_status"] != d["delivery_status"]:
            add("LIFECYCLE", "STATUS_OUTCOME_MISMATCH", "order", d["order_id"])
    for o in T["delivery_outcome"]:
        if o["outcome_status"] == "FAILED" and not o["reason_code"]:
            add("ACCEPT", "FAILED_WITHOUT_REASON", "delivery_outcome", o["outcome_id"])
        if o["outcome_status"] == "DELIVERED" and o["reason_code"]:
            add("ACCEPT", "REASON_ON_SUCCESS", "delivery_outcome", o["outcome_id"])
    ev_by = defaultdict(list)
    for e in T["status_event"]:
        ev_by[(e["entity_type"], e["entity_id"])].append(e)
    final = {("DELIVERY", d["delivery_id"]): d["delivery_status"] for d in T["delivery"]}
    final.update({("ROUTE", r["route_id"]): r["route_status"] for r in T["route"]})
    for k, es in ev_by.items():
        es.sort(key=lambda e: e["event_seq"])
        prev, ts_ = None, None
        for i, e in enumerate(es, 1):
            if e["event_seq"] != i or e["from_status"] != prev or e["to_status"] not in schema.TRANSITIONS[k[0]].get(prev, set()) \
                    or (ts_ and e["event_ts"] < ts_):
                add("LIFECYCLE", "INVALID_TRANSITION", "status_event", e["event_id"]); break
            prev, ts_ = e["to_status"], e["event_ts"]
        if final.get(k) is not None and prev != final[k]:
            add("LIFECYCLE", "FINAL_STATE_MISMATCH", k[0].lower(), k[1])
    for k in final:
        if k not in ev_by:
            add("LIFECYCLE", "NO_EVENT_HISTORY", k[0].lower(), k[1])
    seen = defaultdict(list)
    for s in T["customer_site"]:
        seen[(s["latitude"], s["longitude"])].append(s["site_id"])
    for k, v in seen.items():
        if len(v) > 1 and not (set(v) & bad_sites):
            add("DUPLICATE", "DUPLICATE_SITE", "customer_site", v[0])
    for d in T["delivery"]:
        pass
    checks["acceptance_lifecycle_duplicates"] = len(issues) - n0
    return issues, checks


def _count(issues, types):
    return sum(1 for i in issues if i["issue_type"] in types)


def evaluate(issues, gt):
    """Compare detections of injectable rules against ground truth (keyed by issue_type + entity_id)."""
    det_ = {(i["issue_type"], i["entity_id"]) for i in issues if i["issue_type"] in INJECTABLE}
    truth = {(g["issue_type"], g["entity_id"]) for g in gt}
    tp, fp, fn = len(det_ & truth), len(det_ - truth), len(truth - det_)
    collateral = [i for i in issues if i["issue_type"] not in INJECTABLE]
    by = {}
    for t in sorted(INJECTABLE):
        a, b = {x for x in truth if x[0] == t}, {x for x in det_ if x[0] == t}
        by[t] = dict(injected=len(a), detected=len(a & b), false_positives=len(b - a))
    return dict(tp=tp, fp=fp, fn=fn, precision=round(tp / (tp + fp), 4) if tp + fp else 1.0,
                recall=round(tp / (tp + fn), 4) if tp + fn else 1.0, collateral_findings=len(collateral),
                collateral_examples=collateral[:5], by_issue_type=by)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_dir")
    ap.add_argument("--seed", type=int, default=20261022)
    ap.add_argument("--ground-truth")
    a = ap.parse_args()
    T = load_dir(a.csv_dir)
    issues, checks = run_all(T, a.seed)
    print(json.dumps(checks, indent=2))
    by = defaultdict(int)
    for i in issues:
        by[i["issue_type"]] += 1
    print("findings by type:", dict(by))
    if a.ground_truth:
        gt = list(csv.DictReader(open(a.ground_truth)))
        print(json.dumps(evaluate(issues, gt), indent=2))
    return 0 if not issues or a.ground_truth else 1


if __name__ == "__main__":
    sys.exit(main())
