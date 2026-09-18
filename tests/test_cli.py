"""The command line."""

from __future__ import annotations

import pytest

from regexengine.cli import main


def invoke(capsys, *args) -> tuple[int, str, str]:
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_match_runs_every_engine(capsys):
    code, out, _ = invoke(capsys, "match", "a+b", "xaaab")
    assert code == 0
    for engine in ("backtracking", "thompson nfa", "lazy dfa", "python re"):
        assert engine in out
    assert "all engines agree: True" in out


def test_match_on_a_pattern_that_does_not_match(capsys):
    _, out, _ = invoke(capsys, "match", "zzz", "abc")
    assert "all engines agree: True" in out
    assert "False" in out


def test_match_reports_the_backtracking_engine_giving_up(capsys):
    """The point of the whole project, in one line of output."""
    _, out, _ = invoke(capsys, "match", "(a+)+b", "a" * 30, "--limit", "20000")
    assert "GAVE UP" in out
    assert "thompson nfa" in out


def test_the_stdlib_is_skipped_on_a_flagged_pattern_and_long_input(capsys):
    """Python's re is a backtracking engine, so running it on a flagged pattern
    and a long input hangs the tool for minutes. That is the thesis of the
    project, not a demo worth waiting through."""
    _, out, _ = invoke(capsys, "match", "(a+)+b", "a" * 30, "--limit", "20000")
    assert "python re      skipped" in out.replace("  ", " ").replace("  ", " ") or "skipped" in out
    assert "backtracking engine" in out


def test_the_stdlib_still_runs_on_a_safe_pattern(capsys):
    _, out, _ = invoke(capsys, "match", "a+b+c", "a" * 40 + "b")
    assert "skipped" not in out


def test_the_guard_can_be_turned_off(capsys):
    """Short input, so running it is cheap even with the guard disabled."""
    _, out, _ = invoke(capsys, "match", "(a+)+b", "a" * 8, "--stdlib-guard", "0")
    assert "skipped" not in out


def test_groups(capsys):
    code, out, _ = invoke(capsys, "groups", r"(\w+)@(\w+)", "mail user@example now")
    assert code == 0
    assert "group 1: 'user'" in out
    assert "group 2: 'example'" in out


def test_groups_with_no_match_exits_one(capsys):
    code, out, _ = invoke(capsys, "groups", "zzz", "abc")
    assert code == 1
    assert "no match" in out


def test_compile(capsys):
    code, out, _ = invoke(capsys, "compile", "a(b|c)*d")
    assert code == 0
    assert "instructions" in out
    assert "split" in out and "match" in out


def test_check_flags_a_dangerous_pattern(capsys):
    code, out, _ = invoke(capsys, "check", "(a+)+b")
    assert code == 1
    assert "RISK" in out
    assert "nested quantifier" in out


def test_check_passes_a_safe_one(capsys):
    code, out, _ = invoke(capsys, "check", r"^\w+@\w+\.\w+$")
    assert code == 0
    assert out.startswith("ok")


def test_check_takes_several_patterns(capsys):
    code, out, _ = invoke(capsys, "check", "(a+)+b", "a+b+c")
    assert code == 1
    assert "RISK" in out and "ok" in out


def test_check_says_it_is_a_heuristic(capsys):
    """A checker that implies it is complete is worse than no checker."""
    _, out, _ = invoke(capsys, "check", "a+")
    assert "heuristic" in out


def test_redos_shows_the_growth(capsys):
    code, out, _ = invoke(capsys, "redos", "-m", "12")
    assert code == 0
    assert "exponential" in out
    assert "backtracking" in out and "thompson" in out


def test_redos_on_a_safe_pattern_says_so(capsys):
    code, out, _ = invoke(capsys, "redos", "a+b+c", "-u", "ab", "-m", "10")
    assert code == 0
    assert "not an explosion" in out


def test_bench_reports_both_directions(capsys):
    code, out, _ = invoke(capsys, "bench", "-n", "2000")
    assert code == 0
    assert "faster" in out and "slower" in out


def test_an_invalid_pattern_is_reported(capsys):
    code, _, err = invoke(capsys, "compile", "a[bc")
    assert code == 2
    assert "rex:" in err


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_:
        main(["--version"])
    assert exit_.value.code == 0
