"""Receipt: session parsing, cost accounting, claim checking."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipt.claims import BACKED, MOVED, UNBACKED, check     # noqa: E402
from receipt.cost import Cost                                  # noqa: E402
from receipt.report import build, render                       # noqa: E402
from receipt.session import load                                # noqa: E402


def _write(tmp_path, rows):
    p = tmp_path / "s.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return p


def _msg(role, content, usage=None, model=None):
    m = {"role": role, "content": content}
    if usage:
        m["usage"] = usage
    if model:
        m["model"] = model
    return {"message": m}


def _use(tid, name, inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def _res(tid, err=False):
    return {"type": "tool_result", "tool_use_id": tid, "content": "x", "is_error": err}


def _text(t):
    return {"type": "text", "text": t}


# ── cost ─────────────────────────────────────────────────────────────────────

def test_cache_reads_are_priced_at_a_tenth_of_input():
    c = Cost()
    c.add("claude-opus-5", {"cache_read_input_tokens": 1_000_000})
    assert c.usd == pytest.approx(0.50)


def test_cache_writes_are_priced_above_input():
    c = Cost()
    c.add("claude-opus-5", {"cache_creation_input_tokens": 1_000_000})
    assert c.usd == pytest.approx(6.25)


def test_output_dominates_per_token():
    c = Cost()
    c.add("claude-opus-5", {"output_tokens": 1_000_000})
    assert c.usd == pytest.approx(25.00)


def test_cache_share_reveals_re_read_context():
    """A long session is mostly re-read context, which no per-message view shows."""
    c = Cost()
    c.add("claude-opus-5", {"input_tokens": 1000, "cache_read_input_tokens": 99_000})
    assert c.cache_share == pytest.approx(0.99)


def test_an_unknown_model_reports_no_price_rather_than_a_wrong_one():
    c = Cost()
    c.add("some-future-model", {"output_tokens": 1_000_000})
    assert c.known_pricing is False and c.usd == 0.0


def test_synthetic_model_entries_do_not_overwrite_the_real_model():
    c = Cost()
    c.add("claude-opus-5", {"output_tokens": 10})
    c.add("<synthetic>", {"output_tokens": 10})
    assert c.model == "claude-opus-5"


# ── session ──────────────────────────────────────────────────────────────────

def test_failed_calls_are_marked_from_their_result(tmp_path):
    p = _write(tmp_path, [
        _msg("assistant", [_use("t1", "Bash", {"command": "false"})]),
        _msg("user", [_res("t1", err=True)]),
    ])
    s = load(p)
    assert len(s.failures) == 1 and s.failures[0].name == "Bash"


def test_files_touched_counts_only_writes(tmp_path):
    p = _write(tmp_path, [
        _msg("assistant", [_use("t1", "Edit", {"file_path": "/a/b.py",
                                               "new_string": "x"})]),
        _msg("user", [_res("t1")]),
        _msg("assistant", [_use("t2", "Read", {"file_path": "/a/c.py"})]),
        _msg("user", [_res("t2")]),
    ])
    assert list(load(p).files_touched) == ["/a/b.py"]


def test_test_runs_are_recognised_by_shape_not_only_by_runner(tmp_path):
    p = _write(tmp_path, [
        _msg("assistant", [_use("t1", "Bash",
                                {"command": "python -c 'import tests.test_x'"})]),
        _msg("user", [_res("t1")]),
    ])
    assert len(load(p).test_runs) == 1


# ── claims ───────────────────────────────────────────────────────────────────

def test_narration_is_not_a_completion_claim(tmp_path):
    p = _write(tmp_path, [_msg("assistant", [_text("Now the config file.")])])
    assert check(load(p)) == []


def test_a_claim_after_a_successful_write_is_backed(tmp_path, monkeypatch):
    f = tmp_path / "a.py"
    f.write_text("hello", encoding="utf-8")
    p = _write(tmp_path, [
        _msg("assistant", [_use("t1", "Write", {"file_path": str(f),
                                                "content": "hello"})]),
        _msg("user", [_res("t1")]),
        _msg("assistant", [_text("The config is done.")]),
    ])
    assert [c.status for c in check(load(p))] == [BACKED]


def test_a_claim_after_a_failed_write_that_never_landed_is_unbacked(tmp_path):
    missing = tmp_path / "gone.py"
    p = _write(tmp_path, [
        _msg("assistant", [_use("t1", "Write", {"file_path": str(missing),
                                                "content": "scheme"})]),
        _msg("user", [_res("t1", err=True)]),
        _msg("assistant", [_text("Native scaffolding is done.")]),
    ])
    [c] = check(load(p))
    assert c.status == UNBACKED and "does not exist" in c.detail


# ── report ───────────────────────────────────────────────────────────────────

def test_the_receipt_never_invents_a_bill(tmp_path):
    """A Claude Code subscription is not billed per token. Printing a dollar
    figure without saying so reports a charge the user never received."""
    p = _write(tmp_path, [
        _msg("assistant", [_text("Done.")],
             usage={"output_tokens": 1000}, model="claude-opus-5"),
    ])
    out = render(build(load(p)))
    assert "at API list prices" in out
    assert "not billed per token" in out
