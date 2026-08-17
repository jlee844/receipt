"""Find and read a Claude Code session transcript."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}
_TEST = re.compile(r"\b(pytest|jest|vitest|go test|cargo test|npm (run )?test|"
                   r"unittest|tox|rspec)\b|test_[\w-]+\.\w+|\btests?[/.]", re.I)


def current_session_id() -> str | None:
    """The session this process is running inside, if any.

    Claude Code exports CLAUDE_CODE_SESSION_ID into every tool call, so an
    agent identifies itself with no configuration and no guessing. This is what
    makes several sessions in ONE directory unambiguous — picking the most
    recently modified transcript silently returns whichever session typed last.
    """
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    return sid or None


def for_session(sid: str) -> Path | None:
    """The transcript for a specific session id, wherever it lives."""
    if not PROJECTS.exists():
        return None
    hits = list(PROJECTS.glob(f"*/{sid}.jsonl"))
    return hits[0] if hits else None


def live_sessions() -> list[dict]:
    """Every Claude Code session currently running, with its directory.

    Each live session owns a socket named for its pid; the pid's cwd says which
    project it is working in. Two sessions in the same directory are normal.
    """
    out = []
    for sock in sorted(Path("/tmp/cc-socks").glob("*.sock")) if Path("/tmp/cc-socks").exists() else []:
        pid = sock.stem
        if not pid.isdigit():
            continue
        if subprocess.run(["ps", "-p", pid], capture_output=True).returncode != 0:
            continue
        r = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"],
                           capture_output=True, text=True)
        cwd = next((l[1:] for l in r.stdout.splitlines() if l.startswith("n")), "")
        out.append({"pid": int(pid), "cwd": cwd})
    return out


def slug(cwd: Path) -> str:
    return "-" + str(cwd.resolve()).replace("/", "-").lstrip("-")


def latest(cwd: Path | None = None) -> tuple[Path | None, bool]:
    """Most recent transcript for `cwd`, else the most recent anywhere.

    Returns (path, matched_cwd). The fallback used to be silent, so running
    this outside a project reported another project's work with nothing on
    screen saying so.
    """
    if not PROJECTS.exists():
        return None, False
    matched = True
    candidates: list[Path] = []
    if cwd:
        d = PROJECTS / slug(cwd)
        if d.exists():
            candidates = [p for p in d.glob("*.jsonl") if p.stat().st_size > 2000]
    if not candidates:
        matched = False
        candidates = [p for p in PROJECTS.glob("*/*.jsonl") if p.stat().st_size > 2000]
    if not candidates:
        return None, False
    return max(candidates, key=lambda p: p.stat().st_mtime), matched


@dataclass
class Call:
    index: int               # position in the stream; support must precede a claim
    name: str
    target: str
    ok: bool
    attempted: str = ""      # truncated: only used to probe a file's contents
    input_chars: int = 0     # real size, before truncation
    result_chars: int = 0    # what came BACK — usually the larger cost


@dataclass
class Session:
    path: Path
    session_id: str
    matched_cwd: bool = True   # False when we fell back to any project
    calls: list[Call] = field(default_factory=list)
    prose: list[tuple[int, str]] = field(default_factory=list)
    usage: list[tuple[str, dict]] = field(default_factory=list)
    user_turns: int = 0

    @property
    def files_touched(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.calls:
            if c.name in WRITE_TOOLS and c.target:
                out[c.target] = out.get(c.target, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    @property
    def test_runs(self) -> list[Call]:
        return [c for c in self.calls if _TEST.search(c.target)]

    @property
    def failures(self) -> list[Call]:
        return [c for c in self.calls if not c.ok]


def _target(inp: dict) -> str:
    for k in ("file_path", "command", "notebook_path", "pattern", "url"):
        v = inp.get(k)
        if isinstance(v, str) and v.strip():
            return " ".join(v.split())
    return ""


def load(path: Path) -> Session:
    s = Session(path=path, session_id=path.stem)
    pending: dict[str, Call] = {}
    idx = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = rec.get("message") or {}
        role, content = msg.get("role"), msg.get("content")
        if msg.get("usage"):
            s.usage.append((msg.get("model") or "", msg["usage"]))
        blocks = ([{"type": "text", "text": content}] if isinstance(content, str)
                  else content if isinstance(content, list) else [])
        for b in blocks:
            if not isinstance(b, dict):
                continue
            idx += 1
            t = b.get("type")
            if t == "tool_use":
                inp = b.get("input") or {}
                whole = str(inp.get("new_string") or inp.get("content") or "")
                c = Call(idx, b.get("name") or "?", _target(inp), True,
                         whole[:2000], input_chars=len(json.dumps(inp)))
                pending[b.get("id")] = c
                s.calls.append(c)
            elif t == "tool_result":
                c = pending.get(b.get("tool_use_id"))
                if c:
                    c.result_chars = len(str(b.get("content") or ""))
                    if b.get("is_error"):
                        c.ok = False
            elif t == "text" and (b.get("text") or "").strip():
                if role == "assistant":
                    s.prose.append((idx, b["text"]))
                else:
                    s.user_turns += 1
    return s
