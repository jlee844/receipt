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
pip install agent-receipt
receipt                    # latest session for this directory
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

## The two lines people stop at

**`cache re-read … 97% of all input`.** A long session is almost entirely the
model re-reading its own context. Nothing in a per-message view shows this, and
it is where the money goes.

**`NOT BACKED`.** A completion claim — *"the config is done"*, *"all tests
pass"* — where the write that should support it failed and the change is still
not on disk. Measured across 1,135 real claims, **98.0% were backed**. The
remaining 2% is the part worth reading, and one of them had been quietly wrong
for four weeks.

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
python -m pytest tests/ -q     # 13 tests, no network
```

One of them asserts the receipt never prints a dollar figure without saying a
subscription is not billed per token — because the first version did, and a
$222 number with no context is a charge you never received.
