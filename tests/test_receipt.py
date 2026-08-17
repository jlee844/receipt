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
    tmp_path.mkdir(parents=True, exist_ok=True)
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


# ── waste ────────────────────────────────────────────────────────────────────

from receipt.waste import profile, repeated_reads   # noqa: E402


def _big(tmp_path, n_calls, big_at, big_chars=40_000):
    rows = []
    for i in range(n_calls):
        rows.append(_msg("assistant", [_use(f"t{i}", "Read",
                                            {"file_path": f"/a/f{i}.py"})]))
        size = big_chars if i == big_at else 100
        rows.append({"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": "x" * size}]}})
    return _write(tmp_path, rows)


def test_cost_is_size_times_how_long_it_stayed_in_context(tmp_path):
    """The same read early costs far more than late — it is re-read on every
    later turn. Ranking by raw size alone misses this entirely."""
    early = profile(load(_big(tmp_path / "e", 40, big_at=2)), top=1)[0]
    late = profile(load(_big(tmp_path / "l", 40, big_at=37)), top=1)[0]
    assert early.tokens == late.tokens
    assert early.carry_tokens > late.carry_tokens * 5


def test_result_size_is_counted_not_just_what_was_sent(tmp_path):
    """Truncating to probe a file's contents made every row read 500 tokens
    and turned the ranking into turn order wearing a number."""
    [top] = profile(load(_big(tmp_path, 10, big_at=1)), top=1)
    assert top.tokens > 5_000


def test_trivial_results_are_not_ranked(tmp_path):
    rows = [_msg("assistant", [_use("t0", "Bash", {"command": "ls"})]),
            {"message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t0", "content": "ok"}]}}]
    assert profile(load(_write(tmp_path, rows))) == []


def test_repeated_opens_are_surfaced(tmp_path):
    rows = []
    for i in range(3):
        rows.append(_msg("assistant", [_use(f"t{i}", "Edit",
                                            {"file_path": "/a/same.py",
                                             "new_string": "x"})]))
        rows.append(_msg("user", [_res(f"t{i}")]))
    assert repeated_reads(load(_write(tmp_path, rows))) == [("same.py", 3)]


# ── regressions for a shipped bug (found by an outside reviewer) ─────────────

from receipt.claims import NO_SUPPORT   # noqa: E402


def test_a_claim_with_no_tool_call_at_all_is_not_backed(tmp_path):
    """The shipped v0.1 marked these BACKED. A transcript of nothing but
    'All tests pass. The deploy is live.' with zero tool calls scored 100%
    backed — so BACKED meant 'no nearby failed write', not evidence."""
    p = _write(tmp_path, [
        _msg("assistant", [_text("All tests pass.")]),
        _msg("assistant", [_text("The deploy is live.")]),
    ])
    assert [c.status for c in check(load(p))] == [NO_SUPPORT, NO_SUPPORT]


def test_a_later_unrelated_call_cannot_mask_an_earlier_failure(tmp_path):
    """Support was the session's last N calls regardless of position, so 30
    later successes buried a failed write that preceded the claim."""
    missing = tmp_path / "gone.py"
    rows = [
        _msg("assistant", [_use("t1", "Write", {"file_path": str(missing),
                                                "content": "x"})]),
        _msg("user", [_res("t1", err=True)]),
        _msg("assistant", [_text("The config is done.")]),
    ]
    for i in range(30):
        rows += [_msg("assistant", [_use(f"u{i}", "Read",
                                         {"file_path": f"/tmp/x{i}.py"})]),
                 _msg("user", [_res(f"u{i}")])]
    [c] = check(load(_write(tmp_path, rows)))
    assert c.status == UNBACKED


def test_support_never_includes_calls_made_after_the_claim(tmp_path):
    """The invariant behind both bugs above."""
    f = tmp_path / "a.py"
    f.write_text("x", encoding="utf-8")
    p = _write(tmp_path, [
        _msg("assistant", [_text("Everything is done.")]),
        _msg("assistant", [_use("t1", "Write", {"file_path": str(f),
                                                "content": "x"})]),
        _msg("user", [_res("t1")]),
    ])
    assert [c.status for c in check(load(p))] == [NO_SUPPORT]


def test_a_test_claim_with_no_test_run_is_flagged(tmp_path):
    """The published breakdown has an 'unverified_tests' row; v0.1 could not
    actually produce it — the constant was defined and never assigned."""
    p = _write(tmp_path, [
        _msg("assistant", [_use("t1", "Bash", {"command": "ls -la"})]),
        _msg("user", [_res("t1")]),
        _msg("assistant", [_text("All 11 backend tests pass.")]),
    ])
    from receipt.claims import UNVERIFIED_TESTS
    assert [c.status for c in check(load(p))] == [UNVERIFIED_TESTS]


def test_a_hand_rolled_harness_counts_as_running_tests(tmp_path):
    p = _write(tmp_path, [
        _msg("assistant", [_use("t1", "Bash",
                                {"command": "python3 -c 'import tests.test_x'"})]),
        _msg("user", [_res("t1")]),
        _msg("assistant", [_text("All 11 backend tests pass.")]),
    ])
    assert [c.status for c in check(load(p))] == [BACKED]


def test_subagent_work_is_uncheckable_not_a_failure(tmp_path):
    p = _write(tmp_path, [
        _msg("assistant", [_use("t1", "Agent", {"command": "run the suite"})]),
        _msg("user", [_res("t1")]),
        _msg("assistant", [_text("All 436 tests passed.")]),
    ])
    from receipt.claims import DELEGATED
    assert [c.status for c in check(load(p))] == [DELEGATED]


def test_the_fallback_to_another_project_is_stated_not_silent(tmp_path):
    """Run outside a project, receipt used to report a DIFFERENT project's
    session with nothing on screen saying so."""
    p = _write(tmp_path, [_msg("assistant", [_text("Done.")],
                               usage={"output_tokens": 10}, model="claude-opus-5")])
    s = load(p)
    s.matched_cwd = False
    out = render(build(s))
    assert "no session for this directory" in out


def test_a_matched_session_shows_no_warning(tmp_path):
    p = _write(tmp_path, [_msg("assistant", [_text("Done.")],
                               usage={"output_tokens": 10}, model="claude-opus-5")])
    assert "no session for this directory" not in render(build(load(p)))


# ── multi-session identity ───────────────────────────────────────────────────

def test_the_session_reports_itself_not_whichever_typed_last(tmp_path, monkeypatch):
    """Two sessions in one directory is normal. Picking the newest transcript
    silently reports the other session's work."""
    from receipt.session import current_session_id
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc123-def")
    assert current_session_id() == "abc123-def"


def test_no_session_env_means_no_claim_of_identity(monkeypatch):
    from receipt.session import current_session_id
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    assert current_session_id() is None


def test_blank_session_env_is_treated_as_absent(monkeypatch):
    from receipt.session import current_session_id
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "   ")
    assert current_session_id() is None


def test_for_session_finds_a_transcript_in_any_project_dir(tmp_path, monkeypatch):
    """A session's transcript lives under a slug of its cwd; the lookup must not
    assume which directory that is."""
    import receipt.session as S
    proj = tmp_path / "-some-project"
    proj.mkdir()
    (proj / "sid-xyz.jsonl").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(S, "PROJECTS", tmp_path)
    assert S.for_session("sid-xyz").name == "sid-xyz.jsonl"
    assert S.for_session("not-there") is None
