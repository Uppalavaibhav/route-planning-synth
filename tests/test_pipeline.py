import json, os, re, sqlite3, sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import generator, validate, schema  # noqa: E402


@pytest.fixture(scope="module")
def ds(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("starter"))
    args = generator.argparse.Namespace(scale="starter", seed=20261022, sites=None, deliveries=None, vehicles=None,
                                        days=None, anomalies=None)
    cfg = generator.make_cfg(args)
    T, final_T, gt, summary, man = generator.run(cfg, out)
    return dict(out=out, T=T, F=final_T, gt=gt, summary=summary, man=man, cfg=cfg)


def test_scale_parameters(ds):
    c = ds["man"]["row_counts"]
    assert c["customer_site"] == 51 and c["order"] == c["delivery"] == c["time_window"] == 200 and c["vehicle"] == 12


def test_baseline_has_zero_violations(ds):
    issues, _ = validate.run_all(ds["T"], ds["cfg"]["seed"])
    assert issues == []


def test_all_injected_anomalies_detected_exactly(ds):
    issues, _ = validate.run_all(ds["F"], ds["cfg"]["seed"])
    ev = validate.evaluate(issues, ds["gt"])
    assert ev["fn"] == 0 and ev["fp"] == 0 and ev["collateral_findings"] == 0
    assert {g["issue_type"] for g in ds["gt"]} == validate.INJECTABLE


def test_id_conventions(ds):
    T = ds["F"]
    assert all(re.fullmatch(r"ORD-2026-\d{6}", o["order_id"]) for o in T["order"])
    assert all(re.fullmatch(r"DEL-2026-\d{6}", o["delivery_id"]) for o in T["delivery"])
    assert all(re.fullmatch(r"VEH-\d{6}", o["vehicle_id"]) for o in T["vehicle"])
    assert all(re.fullmatch(r"DRV-\d{6}", o["driver_id"]) for o in T["driver"])
    assert all(re.fullmatch(r"RTE-2026-\d{6}", o["route_id"]) for o in T["route"])
    assert all(re.fullmatch(r"STOP-RTE-2026-\d{6}-\d{3}", o["stop_id"]) for o in T["route_stop"])


def test_ground_truth_not_leaked_into_inputs():
    for n in schema.TABLE_ORDER:
        assert not any(re.search(r"issue_type|ground_truth|anomaly", c) for c in schema.columns(n))


def test_unserved_and_failed_have_reasons(ds):
    T = ds["T"]
    assert any(d["assignment_status"] == "UNSERVED" for d in T["delivery"])
    assert all(d["unserved_reason_code"] for d in T["delivery"] if d["assignment_status"] == "UNSERVED")
    assert all(o["reason_code"] for o in T["delivery_outcome"] if o["outcome_status"] == "FAILED")


def test_reproducible_same_seed(tmp_path):
    out = []
    for i in range(2):
        p = str(tmp_path / f"r{i}")
        assert generator.main(["--scale", "starter", "--out", p]) == 0
        out.append(json.load(open(os.path.join(p, "docs", "dataset_manifest.json"))))
    assert out[0]["row_counts"] == out[1]["row_counts"] and out[0]["sha256"] == out[1]["sha256"]


def test_csv_roundtrip_validation(ds):
    T = validate.load_dir(os.path.join(ds["out"], "csv"))
    issues, _ = validate.run_all(T, ds["cfg"]["seed"])
    ev = validate.evaluate(issues, ds["gt"])
    assert ev["recall"] == 1.0 and ev["precision"] == 1.0


def test_sql_seed_loads(ds):
    con = sqlite3.connect(":memory:")
    con.executescript(open(os.path.join(ds["out"], "sql", "schema.sql")).read().replace("PRAGMA foreign_keys = ON;", ""))
    con.executescript(open(os.path.join(ds["out"], "sql", "seed.sql")).read())
    assert con.execute("SELECT COUNT(*) FROM delivery").fetchone()[0] == 200
