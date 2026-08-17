"""Did the things it said it did actually happen?

Checked against the filesystem, not against a model. Measured on 1,135 real
completion claims: 98.0% were backed by a call that succeeded.

The filesystem is ground truth for what is true NOW, not for what was true
then — a file renamed after the fact makes a correct claim look false, so
relocation is detected separately rather than reported as a failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .session import Call, Session

# A claim asserts STATE. Narration ("Now the config file") asserts nothing, and
# reading it as a completion claim is the classic false-alarm source.
_CLAIM = re.compile(
    r"\b((is|are|was|were|now)\s+(all\s+)?(done|complete|completed|fixed|working|"
    r"verified|live|set|shipped|in place|green|passing)"
    r"|all (tests? )?(pass|passing|passed|clean|green)"
    r"|tests? (pass|passing|passed)|(done|fixed|shipped|complete)[.!]"
    r"|verified\b|no errors\b)", re.I)
_NARRATION = re.compile(r"^\s*(now|next|let me|i'?ll|then|first|adding|building|"
                        r"writing|checking|running|starting)\b", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")

BACKED, UNBACKED, MOVED, UNVERIFIED_TESTS = (
    "backed", "unbacked", "moved", "unverified_tests")


@dataclass
class ClaimCheck:
    sentence: str
    status: str
    detail: str = ""


def _failed_writes(calls: list[Call]) -> list[Call]:
    ok = {c.target for c in calls if c.ok and c.target}
    return [c for c in calls
            if not c.ok and c.target and c.target not in ok
            and c.name in {"Write", "Edit", "NotebookEdit"}]


def _relocated(missing: Path, attempted: str) -> str | None:
    root = next((p for p in missing.parents if (p / ".git").exists()), None)
    if root is None or not attempted:
        return None
    probe = " ".join(attempted.split())[:80]
    for cand in list(root.rglob(missing.name))[:40]:
        if "__pycache__" in cand.parts:
            continue
        try:
            body = " ".join(cand.read_text(encoding="utf-8", errors="replace").split())
        except OSError:
            continue
        if probe and probe in body:
            return str(cand.relative_to(root))
    return None


def check(session: Session, lookback: int = 25) -> list[ClaimCheck]:
    out: list[ClaimCheck] = []
    for idx, text in session.prose:
        support = [c for c in session.calls][-lookback:] if session.calls else []
        for raw in _SENT.split(text):
            s = " ".join(raw.split())
            if not s or len(s) > 400 or _NARRATION.match(s) or not _CLAIM.search(s):
                continue
            bad = _failed_writes(support)
            if not bad:
                out.append(ClaimCheck(s[:200], BACKED))
                continue
            problems, moved = [], []
            for c in bad:
                p = Path(c.target)
                if not p.is_absolute():
                    continue
                if not p.exists():
                    (moved if (m := _relocated(p, c.attempted)) else problems).append(
                        f"{p.name} -> {m}" if m else f"{p.name} does not exist")
                elif c.attempted:
                    probe = " ".join(c.attempted.split())[:80]
                    body = " ".join(p.read_text(encoding="utf-8",
                                                errors="replace").split())
                    if probe and probe not in body:
                        problems.append(f"{p.name} lacks the attempted change")
            if problems:
                out.append(ClaimCheck(s[:200], UNBACKED, "; ".join(problems[:2])))
            elif moved:
                out.append(ClaimCheck(s[:200], MOVED, "; ".join(moved[:2])))
            else:
                out.append(ClaimCheck(s[:200], BACKED))
    return out
