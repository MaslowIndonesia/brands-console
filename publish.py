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
