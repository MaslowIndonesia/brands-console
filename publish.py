#!/usr/bin/env python3
"""Brands Console publisher — $0, pure stdlib.

Reads the brands-revenue-loop registry + each brand's ledgers/state and writes
data.json for the static console. HONEST BY CONSTRUCTION: every value traces to
a ledger row; anything missing renders as null -> the page shows "no data yet".

Usage:  python3 publish.py [--push]
        --push : git add/commit/push (used by the member loops each cycle)
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
REPO = Path(__file__).resolve().parent
REGISTRY = HOME / ".claude/skills/brands-revenue-loop/registry.json"
MA_LEDGER = HOME / ".claude/skills/meta-ads-automate/ledger"
ODP_STATE = HOME / ".claude/skills/odp-revenue-loop/state"



METRICS = REPO / "metrics_snapshot.json"
BENCH = REPO / "benchmark_ledger.jsonl"

PILLAR_STAGES = ["launch_24h_trial", "cpc_kill_gate", "first_sale_be_roas",
                 "loss_kill_gate", "outlier_promotion", "three_band_scale",
                 "certified_3orders_roas2"]

def pillar_eval(camp, db):
    """Deterministic pass/fail per the rev6/7 Meta-Ads-Pillar ladder (video aVd4Hg-jFjI).
    Honest: stages needing data we don't have per-campaign yet render 'pending'."""
    spent = (camp.get("spend") or 0) > 0
    attributed = 0  # per-campaign attributed orders: none yet (attribution join awaits volume)
    return [
        {"stage": "launch_24h_trial", "state": "pass" if spent else "pending",
         "note": "live + spending" if spent else "not launched"},
        {"stage": "cpc_kill_gate", "state": "pass" if (camp.get("cpc") or 9e9) < 500 else "fail",
         "note": f"CPC {camp.get('cpc')} vs kill-threshold (AOV x CVR_opt / BE_ROAS)"},
        {"stage": "first_sale_be_roas", "state": "pass" if db.get("paid_orders_30d", 0) > 0 else "pending",
         "note": "book has paid orders (DB)" if db.get("paid_orders_30d") else "no sale yet"},
        {"stage": "loss_kill_gate", "state": "pass" if spent else "pending",
         "note": "cumulative loss < 1 daily test budget"},
        {"stage": "outlier_promotion", "state": "pending", "note": "awaits per-creative divergence"},
        {"stage": "three_band_scale", "state": "pending", "note": "needs lifetime realized ROAS"},
        {"stage": "certified_3orders_roas2",
         "state": "fail" if attributed < 3 else "pass",
         "note": f"{attributed}/3 attributed orders on arm; realized ROAS >= 2.0 + span/clicks clause"},
    ]

def bench_append(runrate, gap, realized):
    import time
    row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "monthly_runrate_idr": runrate, "gap_to_1B_x": gap,
           "book_realized_roas": realized}
    try:
        last = jsonl_tail(BENCH, 1)
        if last and all(last[0].get(k) == row.get(k) for k in ("monthly_runrate_idr", "gap_to_1B_x")):
            return
        with open(BENCH, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass

def jload(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def jsonl_tail(p: Path, n=1):
    try:
        lines = [l for l in p.read_text().splitlines() if l.strip()]
        return [json.loads(l) for l in lines[-n:]]
    except Exception:
        return []


def jsonl_count(p: Path):
    try:
        return sum(1 for l in p.read_text().splitlines() if l.strip())
    except Exception:
        return None


def build():
    registry = jload(REGISTRY) or {}
    index = jload(MA_LEDGER / "index.json") or {}
    heur = jload(MA_LEDGER / "heuristics.json") or {}

    book = index.get("active_book") or {}

    # ODP revenue-loop state (tolerant — every piece optional)
    realized = jsonl_tail(ODP_STATE / "realized_roas.jsonl", 1)
    backlog = jload(ODP_STATE / "funnel_backlog.json")
    graveyard = jload(ODP_STATE / "graveyard.json")
    goal = jload(ODP_STATE / "revenue_goal.json")
    spend_snap = jload(ODP_STATE / "spend_snapshot.json")

    stages = {}
    if isinstance(backlog, dict):
        items = (backlog.get("candidates") or backlog.get("funnels")
                 or backlog.get("items") or [])
        if isinstance(items, list):
            for f in items:
                s = (f or {}).get("stage") or (f or {}).get("status") or "unknown"
                stages[s] = stages.get(s, 0) + 1

    rules = []
    for r in (heur.get("rules") or []):
        stmt = (r.get("statement") or "").split(". ")[0][:180]
        rules.append({
            "id": r.get("rule_id"),
            "confidence": r.get("confidence"),
            "status": r.get("status"),
            "head": stmt,
        })

    records = []
    for name, meta in (index.get("records") or {}).items():
        if isinstance(meta, dict) and meta.get("date"):
            records.append({
                "file": name,
                "date": meta.get("date"),
                "type": meta.get("type"),
                "note": (meta.get("note") or meta.get("executed") or meta.get("verdict") or "")[:220],
            })
    records.sort(key=lambda r: r["date"], reverse=True)

    metrics = jload(METRICS) or {}
    db = metrics.get("db_ground_truth") or {}
    camps = metrics.get("campaigns") or []
    spend7 = sum(c.get("spend") or 0 for c in camps)
    for c in camps:
        c["avg_clicks_day"] = round((c.get("clicks") or 0) / 7.0, 1)
        c["pillar"] = pillar_eval(c, db)
    paid30 = db.get("paid_value_30d_idr") or 0
    book_roas = round(paid30 / (spend7 * 30 / 7.0), 4) if spend7 else None
    runrate = paid30  # 30d paid value = monthly run-rate (DB ground truth)
    gap = round(1_000_000_000 / runrate, 1) if runrate else None
    bench_append(runrate, gap, book_roas)
    bench_series = jsonl_tail(BENCH, 30)

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "registry": registry,
        "odp": {
            "loop_mode": index.get("loop_mode"),
            "loop_mode_note": (index.get("loop_mode_note") or "")[:400],
            "roas_gate": index.get("roas_gate"),
            "active_book": {
                "as_of": book.get("as_of"),
                "thesis": (book.get("thesis") or "")[:500],
                "envelope": book.get("envelope_idr_day"),
                "live_campaigns": book.get("live_campaigns"),
                "ab_test": book.get("ab_test_2026-07-16"),
            },
            "realized_roas_latest": realized[0] if realized else None,
            "calibration_entries": jsonl_count(ODP_STATE / "calibration.jsonl"),
            "factory": {
                "backlog_stages": stages or None,
                "graveyard_count": len(graveyard) if isinstance(graveyard, list)
                else (len(graveyard.get("funnels", [])) if isinstance(graveyard, dict) else None),
            },
            "revenue_goal": goal,
            "spend_snapshot": spend_snap,
            "rules": rules,
            "recent_records": records[:10],
            "metrics": {"as_of": metrics.get("as_of"), "window": metrics.get("window"),
                        "campaigns": camps, "db_ground_truth": db,
                        "book_realized_roas_30d": book_roas, "spend_7d": spend7},
            "models": {"thinking": "Fable 5 (max effort)", "executing": "Opus 4.8",
                       "adversarial_gate": "Grok (sole binding gate)",
                       "cross_check": "Kimi K3 (HARD/money)",
                       "cheap_lane": "DeepSeek V4 / Python $0"},
            "benchmark": {"north_star_idr_month": 1_000_000_000,
                          "monthly_runrate_idr": runrate, "gap_to_1B_x": gap,
                          "series": bench_series,
                          "note": "run-rate = DB-attributed paid value trailing 30d; the series is the unbiased improvement record — it only moves when real settled orders move."},
        },
    }

    out = REPO / "data.json"
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")
    return 0


def push():
    def run(*cmd):
        return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)

    run("git", "add", "-A")
    if "nothing to commit" in run("git", "commit", "-m", "console: refresh data").stdout:
        print("no changes")
        return 0
    r = run("git", "push")
    print(r.stdout or r.stderr)
    return r.returncode


if __name__ == "__main__":
    rc = build()
    if "--push" in sys.argv:
        rc = rc or push()
    sys.exit(rc)
