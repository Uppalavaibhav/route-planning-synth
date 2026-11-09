#!/usr/bin/env python3
"""Regenerate twice with the same seed and compare row counts + SHA-256 checksums (Step 10)."""
import argparse, json, os, sys, tempfile
import generator


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", default="full")
    ap.add_argument("--seed", type=int, default=20261022)
    ap.add_argument("--report", default=None)
    a = ap.parse_args()
    runs = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in (1, 2):
            out = os.path.join(tmp, f"run{i}")
            generator.main(["--scale", a.scale, "--seed", str(a.seed), "--out", out])
            m = json.load(open(os.path.join(out, "docs", "dataset_manifest.json")))
            runs.append(m)
        other = os.path.join(tmp, "run3")
        generator.main(["--scale", a.scale, "--seed", str(a.seed + 1), "--out", other])
        diff = json.load(open(os.path.join(other, "docs", "dataset_manifest.json")))
    same_rows = runs[0]["row_counts"] == runs[1]["row_counts"]
    same_hash = runs[0]["sha256"] == runs[1]["sha256"]
    rep = dict(scale=a.scale, seed=a.seed, run1_row_counts=runs[0]["row_counts"], run2_row_counts=runs[1]["row_counts"],
               row_counts_identical=same_rows, files_compared=len(runs[0]["sha256"]), checksums_identical=same_hash,
               mismatched_files=[k for k in runs[0]["sha256"] if runs[0]["sha256"][k] != runs[1]["sha256"].get(k)],
               sample_checksums={k: v for k, v in list(runs[0]["sha256"].items())[:5]},
               control_different_seed_differs=runs[0]["sha256"] != diff["sha256"],
               result="PASS" if same_rows and same_hash else "FAIL")
    print(json.dumps({k: rep[k] for k in ("scale", "seed", "row_counts_identical", "files_compared", "checksums_identical", "control_different_seed_differs", "result")}, indent=2))
    if a.report:
        os.makedirs(os.path.dirname(a.report), exist_ok=True)
        json.dump(rep, open(a.report, "w"), indent=2)
    return 0 if rep["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
