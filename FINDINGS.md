# I checked 1,135 things an AI agent said it had done

Fifteen needed a human to look at them. Two were flatly false — and one of those
had been quietly wrong for four weeks.

This is what I found after pointing a checker at my own agent sessions, and the
five things I tried first that didn't work.

---

## The thing I wanted to build

AI coding agents wander. You ask for one thing, two hours later they're deep in
something else, and you don't notice until you read the summary — which is
written by the thing being summarised.

So I wanted a tool that watches the work and taps you on the shoulder: *this
isn't what you asked for.*

A tool like that is only useful if it's **right**. One that cries wolf gets
switched off in a day. Nobody had published accuracy numbers for this, so
before building anything on top, I tried to find out.

## Five attempts, all failures

Each was scored against nine real moments where I'd gone off track — the times
a human stepped in and redirected the agent.

| attempt | result |
|---|---|
| Is it talking more than doing? | 53 alarms, right **once** |
| Have the words changed? | 12 alarms, right **zero** times |
| Ask a frontier model "is this on track?" | missed the case that mattered |
| Ask again, with the whole session and a better schema | **missed it again** |
| Segment the work by structure, not words | **0 of 7** sessions beat random |

Total spend across all five: **$1.10**. Every one had its prediction and its
kill condition written down *before* the money was spent, which is the only
reason the results mean anything — twice I was sure the fix would work, and
twice I couldn't quietly redefine success afterwards.

## Why all five failed

Every detector was looking for a change of subject. **The subject never
changed.**

The drift I was trying to catch was on-topic the whole time. What actually went
wrong was that I'd built a measuring instrument far too small for the thing
being measured.

> Like measuring a highway with a 30-centimetre ruler. Still about roads. Still
> measuring. Completely useless — and nothing about the *topic* tells you so.

The sessions ran to thousands of turns. The tool looked at forty at a time.

And here's the part that stung: **the warning was already in the transcript.**
About 150 turns earlier, the agent had written *"these sessions run 8,000 turns,
so measuring in 100-turn chunks is meaningless"* — and then built a 40-turn
tool. No detector caught it, because they all read a narrow slice and the two
halves of the contradiction were 150 turns apart.

### The obvious statistics don't save you either

The natural next move is clustering, PCA, or an outlier detector. I measured
whether that could work.

It can't, and the reason is clean: **two statements that contradict each other
are almost always about the same subject.** The contradicting pair scored in the
**top 9% for similarity** within its own session. An outlier detector ranks it
as one of the most *normal* things there.

Those tools find what stands out. Contradictions blend in.

## What worked

I stopped asking a hard question and started asking an easy one.

| question | needs | result |
|---|---|---|
| Is this the **right** work? | judgment, and knowledge of intent | failed 5 times |
| Did the thing it said it did **actually happen**? | opening the file | works |

The second one is answerable by `open()`. Applied to 1,135 completion claims —
statements like *"the config is done"* or *"all tests pass"*:

```
                       count       of 1,135
backed by a real call    1,112   98.0%
claimed tests passed        13    1.1%   nothing test-shaped ran
done by a sub-agent          6    0.5%   invisible from here
file renamed since           2    0.2%   the work happened, elsewhere
never happened               2    0.2%   claimed, still missing
```

**1,135 claims down to 15 worth a human's attention** — the 13 that claimed
passing tests with nothing test-shaped run, plus the 2 that never happened. The
other 8 non-backed rows are fine: a sub-agent did the work, or a file was
renamed after the fact. **Only those 2 are outright false**, and one was an app config
reported as set up which still carried another project's settings and none of
the ones it claimed. That had been live for four weeks. One filesystem read
settled what an hour of model judgment couldn't.

## The second number people don't expect

Once you're reading the transcript anyway, the token accounting falls out:

```
new input              4,001
cache written      8,863,507
cache re-read    271,167,028   97% of all input
output             1,251,094
```

**97% of the input was the model re-reading its own context.** No per-message
view shows this. It's where the money goes.

And ranking what caused it by size is the wrong metric — a large result costs
you once on arrival and **again on every later turn**, because it sits in
context being re-read:

```
what                     tokens   at turn      carried
a PNG screenshot        102,941        40   41,485,223
a browser screenshot     33,468       125   10,642,824
```

`carried = tokens × turns it stayed in context`. Reading images into context
early was, by an order of magnitude, the most expensive habit in that session.

## What I actually shipped

Two tools, both from failures rather than plans.

**[receipt](https://github.com/jlee844/receipt)** — what a session did, what it
cost, and which of its claims are backed. Reads the transcript instead of
trusting the summary.

**[blindspot](https://github.com/jlee844/blindspot)** — which lines in a diff
would a test actually catch a bug in. Coverage says a line *ran*; it doesn't say
anything asserted on it. This breaks each changed line on purpose and re-runs
only the tests that cover it. A line counts as verified when a test **fails**.

**[transcript-audit](https://github.com/jlee844/transcript-audit)** — profile an
agent-transcript corpus before computing any statistic over it. I needed this
because my own corpus turned out to be **9 usable sessions, not 434**: most were
empty, too short, or an automated bot whose presence moved a headline number
from 0.57 to 1.00.

## The rule I'd keep

> Only build a checker when the evidence it needs already exists outside
> anyone's opinion.

"Is this the right work?" needs a judgment call, and everything I built on that
premise failed. "Does this file contain what you said you put in it?" doesn't,
and it worked on the first try.

## Honest limits

- **Claude Code only** for `receipt`. Cursor stores a flattened text search
  index with no tool calls or error flags; Codex keeps no local session
  transcripts. I checked before building, not after.
- **The filesystem is truth for now, not for then.** A file renamed after the
  fact makes a correct claim look false. Renames are detected; deletions are
  indistinguishable from work never done.
- **The cost figure is API list pricing.** A Claude Code subscription is not
  billed per token, so it's what the same work *would* cost through the API —
  not a bill anyone received.
- **`blindspot` is Python and pytest.** A GUARDED verdict is evidence one
  mutation was caught, not proof the line is fully specified.
- **This is one person's corpus.** Nine sessions, one user, one harness. The
  98% is what I measured, not a law.
