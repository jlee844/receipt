# receipt

**What did that agent session actually do — and what did it cost?**

You finish a long session with an AI coding agent. It gives you a summary. The
summary is written by the thing being summarised.

`receipt` reads the session transcript instead and tells you what actually
happened: which files changed, whether the tests really ran, which calls
failed, which completion claims are backed by a call that succeeded — and where
the tokens went.

No dependencies. Nothing leaves your machine.

```bash
git clone https://github.com/jlee844/receipt && cd receipt
pip install -e .

receipt                    # THIS session, auto-detected
receipt --dashboard        # live page: every running session
receipt --live             # list running sessions
receipt --json
```

```
  RECEIPT  be17144b

    you asked                63 times
    tool calls               439
    files changed            43
      llm_judge.py                               9x
      spec-mission-layer.md                      8x
      label.html                                 7x
      …and 40 more

    test runs                105
    calls that failed        17
      Bash 8, Browser 5, javascript 2, SendUserFile 1

    completion claims        78
      backed by a real call  78

    tokens
      new input              4,001
      cache written          8,863,507
      cache re-read          271,167,028   97% of all input
      output                 1,251,094

    at API list prices       $222.28   (claude-opus-5)
    (a Claude Code subscription is not billed per token —
     this is what the same work would cost through the API)
```

## Several sessions at once

Running two agents in one directory is normal — one on the sub-project, one that
needs the parent repo. `receipt` reads the session id Claude Code exports into
every tool call, so it reports **the session it is running inside**, not
whichever transcript in that directory was touched most recently. No config, no
flags, no collisions.

```bash
receipt --dashboard      # http://127.0.0.1:8974
```

One page, a tab per live session, refreshing every few seconds. Each tab shows
what that session is working on (the last things you actually typed), its
activity, every claim checked against disk with the unbacked ones quoted, the
token split, its most-touched files, and what cost the most to carry.
Localhost only; reads transcripts, writes nothing.

It reports the **directory** and how many processes are live in it, never a pid
per session — several Claude processes share a working directory and nothing on
disk links one to a transcript, so a pid per session would be a plausible lie.

## The two lines people stop at

**`cache re-read … 97% of all input`.** A long session is almost entirely the
model re-reading its own context. Nothing in a per-message view shows this, and
it is where the money goes.

**`NOT BACKED`.** A completion claim — *"the config is done"*, *"all tests
pass"* — where the write that should support it failed and the change is still
not on disk. Measured across 1,135 real claims, **98.0% were backed**. The
remaining 2% is the part worth reading, and one of them had been quietly wrong
for four weeks.

## Where the context went

```bash
receipt --waste
```

```
  what                                    tokens   at turn      carried
  b3_baseline.png                        102,941        40   41,485,223
  browser screenshot                      33,468       125   10,642,824
  execution_drift.png                     24,408        35    9,958,464

  opened more than once
  llm_judge.py                                 9x
  spec-mission-layer.md                        8x
```

**The obvious metric is the wrong one.** Ranking tool results by size misses
that a large result costs you once when it arrives and *again on every later
turn*, because it sits in context being re-read. A 100 KB image read at turn 40
of 440 is far more expensive than the same image at turn 430.

    carried  =  tokens  x  turns it stayed in context

On the session above, one PNG read early dominates everything else in the run.
Reading images into context is the single most expensive habit this surfaces.

An estimate, not a bill: compaction drops earlier turns, and images are counted
from encoded size rather than by dimensions.

## What it will not do

**It does not invent a bill.** A Claude Code subscription is not billed per
token, so the figure is labelled as API list pricing and says so on the same
screen. An unknown model prints no price at all rather than a wrong one.

**It does not judge whether the work was *right*.** That question needs your
intent, and five attempts to answer it mechanically all failed. This only
answers whether what was claimed actually happened — a question `open()` can
settle.

## Honest limits

- **Claude Code only.** Cursor stores a flattened text search index with no tool
  calls or error flags, and Codex keeps no session transcripts locally. The
  structure this needs exists in Claude Code's JSONL and nowhere else I checked.
- **The filesystem is truth for now, not for then.** A file renamed after the
  work makes a correct claim look false; relocation is detected and reported
  separately as `moved`, but a deletion is indistinguishable from work never done.
- **Sub-agent work is invisible** — it runs in its own transcript.
- Prices are a static table and go stale. `receipt/cost.py`, one dict.

## In CI

```bash
receipt --fail-on-unbacked
```

Exits 1 if any completion claim in the session is unbacked.

## Tests

```bash
pip install -e ".[dev]" && python -m pytest tests/ -q   # 32 tests, no network
```

Three are regressions for a bug an outside reviewer found in v0.1: support
for a claim was taken from the session's last 25 calls regardless of position,
so a later call masked an earlier failure and a transcript with no tool calls
at all scored every claim `backed`. Another asserts the receipt never prints a
dollar figure without saying a
subscription is not billed per token — because the first version did, and a
$222 number with no context is a charge you never received.

## Why this exists

[**I checked 1,135 things an AI agent said it had done**](FINDINGS.md) —
fifteen weren't true, and five earlier attempts to catch the problem a smarter
way all failed first.

## Status

Not on PyPI yet — install from source as above. Python 3.10+.
