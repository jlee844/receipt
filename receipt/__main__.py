"""receipt — what did that agent session actually do?

    python -m receipt                 # latest session for this directory
    python -m receipt --json
    python -m receipt --fail-on-unbacked
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .report import build, render
from .session import latest, load


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="receipt")
    ap.add_argument("--session", default=None, help="path to a transcript")
    ap.add_argument("--cwd", default=".", help="project dir to find a session for")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on-unbacked", action="store_true",
                    help="exit 1 if any completion claim is unbacked")
    a = ap.parse_args(argv)

    path = Path(a.session) if a.session else latest(Path(a.cwd))
    if not path or not path.exists():
        print("  no session transcript found")
        return 0

    r = build(load(path))
    if a.json:
        json.dump({"session": r.session.session_id,
                   "files_changed": r.session.files_touched,
                   "tool_calls": len(r.session.calls),
                   "failed_calls": len(r.session.failures),
                   "test_runs": len(r.session.test_runs),
                   "claims": [asdict(c) for c in r.claims],
                   "unbacked": len(r.unbacked),
                   "cost": {**asdict(r.cost), "usd": round(r.cost.usd, 4),
                            "cache_share": round(r.cost.cache_share, 4)}},
                  sys.stdout, indent=2)
        print()
    else:
        print(render(r))
    return 1 if (a.fail_on_unbacked and r.unbacked) else 0


if __name__ == "__main__":
    raise SystemExit(main())
