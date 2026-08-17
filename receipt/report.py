"""The receipt: what this session actually did, and what it cost."""

from __future__ import annotations

import collections
from dataclasses import dataclass, field

from .claims import BACKED, MOVED, UNBACKED, ClaimCheck, check
from .cost import Cost
from .session import Session


@dataclass
class Receipt:
    session: Session
    claims: list[ClaimCheck] = field(default_factory=list)
    cost: Cost = field(default_factory=Cost)

    @property
    def unbacked(self) -> list[ClaimCheck]:
        return [c for c in self.claims if c.status == UNBACKED]

    @property
    def moved(self) -> list[ClaimCheck]:
        return [c for c in self.claims if c.status == MOVED]


def build(session: Session) -> Receipt:
    cost = Cost()
    for model, usage in session.usage:
        cost.add(model, usage)
    return Receipt(session=session, claims=check(session), cost=cost)


def _n(x: int) -> str:
    return f"{x:,}"


def render(r: Receipt) -> str:
    s, c = r.session, r.cost
    files = s.files_touched
    tests = s.test_runs
    fails = s.failures
    backed = sum(1 for x in r.claims if x.status == BACKED)

    L = ["", f"  RECEIPT  {s.session_id[:8]}", ""]
    L.append(f"    you asked                {s.user_turns} times")
    L.append(f"    tool calls               {_n(len(s.calls))}")
    L.append(f"    files changed            {len(files)}")
    for name, n in list(files.items())[:5]:
        L.append(f"      {name.split('/')[-1][:40]:<42} {n}x")
    if len(files) > 5:
        L.append(f"      …and {len(files) - 5} more")

    L += ["", f"    test runs                {len(tests)}"]
    L.append(f"    calls that failed        {len(fails)}")
    if fails:
        by = collections.Counter(f.name for f in fails)
        L.append(f"      {', '.join(f'{k} {v}' for k, v in by.most_common(4))}")

    L += ["", f"    completion claims        {len(r.claims)}"]
    L.append(f"      backed by a real call  {backed}")
    if r.moved:
        L.append(f"      file moved since       {len(r.moved)}")
    if r.unbacked:
        L.append(f"      NOT BACKED             {len(r.unbacked)}   <- read these")
        for x in r.unbacked[:4]:
            L.append(f'        "{x.sentence[:90]}"')
            L.append(f"          {x.detail[:90]}")

    L += ["", "    tokens"]
    L.append(f"      new input              {_n(c.input_tokens)}")
    L.append(f"      cache written          {_n(c.cache_write)}")
    L.append(f"      cache re-read          {_n(c.cache_read)}   "
             f"{c.cache_share:.0%} of all input")
    L.append(f"      output                 {_n(c.output_tokens)}")
    # Claude Code subscriptions are not billed per token. Printing a dollar
    # figure without saying so invents a bill the user never received.
    if c.known_pricing and c.model:
        L.append(f"\n    at API list prices       ${c.usd:,.2f}   ({c.model})")
        L.append("    (a Claude Code subscription is not billed per token —")
        L.append("     this is what the same work would cost through the API)")
    else:
        L.append(f"\n    cost                     unknown model: {c.model or '?'}")
    L.append("")
    return "\n".join(L)
