"""Where the context went, and what it cost to carry.

The obvious metric — which tool result was biggest — is the wrong one. A large
result costs you once when it arrives and then *again on every later turn*,
because it sits in the context being re-read. So a 50 KB file read at turn 10
of 400 is far more expensive than the same read at turn 390.

    carry cost  ~=  size  x  turns it remained in context

That is an ESTIMATE, not an accounting. Compaction drops earlier context, so a
long session does not really carry its opening turns to the end. It is a
ranking of what to avoid next time, not a bill.
"""

from __future__ import annotations

from dataclasses import dataclass

from .session import Session

CHARS_PER_TOKEN = 4


@dataclass
class Item:
    label: str
    kind: str
    tokens: int
    turn: int
    carried: int          # turns it stayed in context

    @property
    def carry_tokens(self) -> int:
        return self.tokens * self.carried


def profile(session: Session, top: int = 8) -> list[Item]:
    """Rank what entered context by what it cost to keep carrying."""
    items: list[Item] = []
    total_turns = max(len(session.calls), 1)
    for i, call in enumerate(session.calls):
        # What came BACK plus what was sent. Using the truncated `attempted`
        # here made every row read exactly 500 tokens and the ranking became
        # turn order wearing a number.
        size = call.result_chars + call.input_chars
        if size < 400:
            continue
        items.append(Item(
            label=(call.target or call.name).split("/")[-1][:44],
            kind=call.name,
            tokens=size // CHARS_PER_TOKEN,
            turn=i,
            carried=total_turns - i,
        ))
    items.sort(key=lambda x: -x.carry_tokens)
    return items[:top]


def repeated_reads(session: Session, top: int = 8) -> list[tuple[str, int]]:
    """Files opened more than once. Each re-open pays for the same content."""
    counts: dict[str, int] = {}
    for c in session.calls:
        if c.name in ("Read", "Edit", "Write", "NotebookEdit") and c.target:
            counts[c.target] = counts.get(c.target, 0) + 1
    return sorted(((k.split("/")[-1], v) for k, v in counts.items() if v > 1),
                  key=lambda kv: -kv[1])[:top]


def render(session: Session) -> str:
    items = profile(session)
    reps = repeated_reads(session)
    L = ["", "    WHERE THE CONTEXT WENT", "",
         "      carried = tokens x turns they stayed in context",
         "      an estimate, not a bill: compaction drops earlier turns, and",
         "      images are counted from their encoded size, not by dimensions", ""]
    if items:
        L.append(f"      {'what':<46}{'tokens':>9}{'at turn':>9}{'carried':>12}")
        for it in items:
            L.append(f"      {it.label:<46}{it.tokens:>9,}{it.turn:>9}"
                     f"{it.carry_tokens:>12,}")
    if reps:
        L += ["", "      opened more than once"]
        for name, n in reps:
            L.append(f"      {name[:46]:<46}{n:>9}x")
    L.append("")
    return "\n".join(L)
