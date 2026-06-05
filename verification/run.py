#!/usr/bin/env python3
"""The verification gate. Runs the external test suites, maps results onto the
claims ledger, and writes machine-readable STATUS.json + human VERIFICATION.md.

No claim is "verified" by assertion — only because its bound test passed here.

Usage:
    python verification/run.py                 # full gate (core; e2e if not skipped)
    python verification/run.py -m "not e2e"    # pass pytest args through
    python verification/run.py --core          # alias for -m "not e2e"

Exit code 0 iff every must_pass claim is verified.  This is what CI / make verify gate on.
"""
from __future__ import annotations
import json, subprocess, sys, datetime, shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
VDIR = ROOT / "verification"
REPORT = VDIR / ".report.json"
STATUS = VDIR / "STATUS.json"
MD = VDIR / "VERIFICATION.md"
FRONTEND_PUBLIC = ROOT / "frontend" / "public"


def run_pytest(extra_args: list[str]) -> dict:
    """Run pytest with the json-report plugin and return the parsed report."""
    cmd = [sys.executable, "-m", "pytest", "tests",
           "-p", "no:cacheprovider", "--json-report",
           f"--json-report-file={REPORT}", "-q", "--no-header", *extra_args]
    print("→", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT)  # non-zero exit on test failure is expected; we parse the report
    if not REPORT.exists():
        print("!! pytest produced no report — is pytest-json-report installed?", file=sys.stderr)
        return {"tests": []}
    return json.loads(REPORT.read_text())


def outcome_map(report: dict) -> dict[str, dict]:
    """nodeid -> {outcome, duration}. Collect errors count as failing."""
    out = {}
    for t in report.get("tests", []):
        out[t["nodeid"]] = {"outcome": t.get("outcome", "error"),
                            "duration": t.get("call", {}).get("duration", t.get("setup", {}).get("duration", 0.0))}
    # collection errors -> mark the file as failing so its claims don't go green by omission
    for c in report.get("collectors", []):
        if c.get("outcome") == "failed":
            out[c.get("nodeid", "?")] = {"outcome": "failed", "duration": 0.0}
    return out


def match(claim_test: str, outcomes: dict[str, dict]) -> dict | None:
    if claim_test in outcomes:
        return outcomes[claim_test]
    for nodeid, res in outcomes.items():
        if nodeid.endswith(claim_test) or claim_test in nodeid:
            return res
    return None


def classify(res: dict | None) -> str:
    if res is None:
        return "unverified"          # no test ran -> NOT credited
    if res["outcome"] == "passed":
        return "verified"
    if res["outcome"] in ("skipped", "xfailed"):
        return "unverified"
    return "failing"                 # failed / error


def main() -> int:
    args = sys.argv[1:]
    if "--core" in args:
        args = [a for a in args if a != "--core"] + ["-m", "not e2e"]

    claims = yaml.safe_load((VDIR / "claims.yaml").read_text())["claims"]
    report = run_pytest(args)
    outcomes = outcome_map(report)

    rows = []
    for c in claims:
        res = match(c["test"], outcomes)
        status = classify(res)
        rows.append({**c, "status": status,
                     "duration_s": round(res["duration"], 4) if res else None})

    verified = [r for r in rows if r["status"] == "verified"]
    failing = [r for r in rows if r["status"] == "failing"]
    unverified = [r for r in rows if r["status"] == "unverified"]
    must = [r for r in rows if r["must_pass"]]
    must_green = all(r["status"] == "verified" for r in must)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    status_doc = {
        "generated_at": now,
        "summary": {
            "total": len(rows), "verified": len(verified),
            "failing": len(failing), "unverified": len(unverified),
            "must_pass_total": len(must),
            "must_pass_verified": sum(r["status"] == "verified" for r in must),
            "must_pass_green": must_green,
        },
        "claims": rows,
    }
    STATUS.write_text(json.dumps(status_doc, indent=2))
    # expose to the frontend so the UI badges read real test results
    FRONTEND_PUBLIC.mkdir(parents=True, exist_ok=True)
    shutil.copy(STATUS, FRONTEND_PUBLIC / "status.json")
    write_md(status_doc)

    s = status_doc["summary"]
    print(f"\n{'='*60}")
    print(f"VERIFIED {s['verified']}/{s['total']}  |  failing {s['failing']}  |  unverified {s['unverified']}")
    print(f"must-pass: {s['must_pass_verified']}/{s['must_pass_total']}  ->  "
          f"{'✅ GREEN' if must_green else '❌ NOT GREEN'}")
    print('='*60)
    for r in rows:
        icon = {"verified": "✅", "failing": "❌", "unverified": "⏳"}[r["status"]]
        star = "*" if r["must_pass"] else " "
        print(f"  {icon}{star} [{r['category']:<11}] {r['id']:<22} {r['statement']}")
    return 0 if must_green else 1


def write_md(doc: dict):
    s = doc["summary"]
    lines = ["# Verification status", "",
             f"_Generated {doc['generated_at']} — machine output of `make verify`. "
             "Each claim is credited only because its external test passed._", "",
             f"**Must-pass gate: {'✅ GREEN' if s['must_pass_green'] else '❌ NOT GREEN'}** "
             f"({s['must_pass_verified']}/{s['must_pass_total']}) · "
             f"verified {s['verified']}/{s['total']} · failing {s['failing']} · unverified {s['unverified']}", ""]
    by_cat: dict[str, list] = {}
    for r in doc["claims"]:
        by_cat.setdefault(r["category"], []).append(r)
    for cat, rows in by_cat.items():
        lines += [f"## {cat}", "", "| | claim | test | status |", "|--|--|--|--|"]
        for r in rows:
            icon = {"verified": "✅", "failing": "❌", "unverified": "⏳"}[r["status"]]
            star = " ⭐" if r["must_pass"] else ""
            lines.append(f"| {icon}{star} | {r['statement']} | `{r['test'].split('::')[-1]}` | {r['status']} |")
        lines.append("")
    MD.write_text("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
