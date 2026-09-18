"""Catastrophic backtracking, measured rather than described."""

from __future__ import annotations

import pytest

from regexengine import Backtracking, LazyDFA, Thompson
from regexengine.safety import analyse

EXPLODING = "(a+)+b"


def backtracking_steps(pattern: str, text: str) -> int:
    engine = Backtracking(pattern, limit=200_000_000)
    engine.matches(text)
    return engine.steps


def thompson_steps(pattern: str, text: str) -> int:
    engine = Thompson(pattern)
    engine.matches(text)
    return engine.trace.steps


# -- the exact shape of the explosion ----------------------------------------

@pytest.mark.parametrize("n", range(4, 17))
def test_backtracking_cost_doubles_with_every_character(n):
    """`(a+)+b` against n a's and no b. The closed form is exact, not a fit:
    2^(n+4) - (n+9). Every character added doubles the work."""
    assert backtracking_steps(EXPLODING, "a" * n) == 2 ** (n + 4) - (n + 9)


@pytest.mark.parametrize("n", range(4, 25))
def test_the_automaton_cost_is_linear_in_the_same_case(n):
    """30n - 25, also exact. The pattern's shape costs it nothing."""
    assert thompson_steps(EXPLODING, "a" * n) == 30 * n - 25


def test_the_gap_at_eighteen_characters():
    """Eighteen rather than twenty, because the test suite has to finish: at
    twenty it is 16,777,187 steps and about nine seconds, and `rex redos` will
    show you that on demand."""
    backtracking = backtracking_steps(EXPLODING, "a" * 18)
    automaton = thompson_steps(EXPLODING, "a" * 18)

    assert backtracking == 4_194_277
    assert automaton == 515
    assert backtracking / automaton > 8_000


def test_the_explosion_needs_a_failing_match():
    """Backtracking only explores every path when there is no path that works.
    The same pattern against an input that *does* match returns on the first
    success, which is why a vulnerable pattern can look fine in testing."""
    fails = backtracking_steps(EXPLODING, "a" * 18)
    succeeds = backtracking_steps(EXPLODING, "a" * 18 + "b")

    assert fails == 4_194_277
    assert succeeds == 49
    assert fails / succeeds > 85_000


@pytest.mark.parametrize("pattern", ["(a+)+b", "(a|a)*b", "([a-z]+)*$", r"^(\s*\w+)+$"])
def test_the_known_vulnerable_patterns_really_do_explode(pattern):
    small = backtracking_steps(pattern, "a" * 8 + "!")
    large = backtracking_steps(pattern, "a" * 14 + "!")
    assert (large / small) ** (1 / 6) > 1.9, f"{pattern} grew by only {large / small:.1f}x"


@pytest.mark.parametrize("pattern", ["(a|b)*c", "a+b+c", r"^\w+@\w+\.\w+$", "[a-z]{2,8}[0-9]+"])
def test_the_safe_patterns_stay_linear(pattern):
    small = backtracking_steps(pattern, "ab" * 10 + "!")
    large = backtracking_steps(pattern, "ab" * 16 + "!")
    assert (large / small) ** (1 / 12) < 1.2, f"{pattern} grew by {large / small:.1f}x"


def test_the_automaton_engines_are_flat_on_every_one_of_them():
    for pattern in ["(a+)+b", "(a|a)*b", "([a-z]+)*$", "(a|b)*c"]:
        small = thompson_steps(pattern, "a" * 20)
        large = thompson_steps(pattern, "a" * 40)
        assert large < small * 3, f"{pattern} is not linear in the automaton engine"


def test_the_dfa_is_flat_too():
    engine = LazyDFA(EXPLODING)
    engine.matches("a" * 500)
    assert engine.trace.states_built < 10


# -- the static check --------------------------------------------------------

@pytest.mark.parametrize("pattern", ["(a+)+b", "(a|a)*b", "([a-z]+)*$", "(.*)*x", r"^(\s*\w+)+$"])
def test_the_checker_flags_the_dangerous_shapes(pattern):
    assert analyse(pattern), f"{pattern} should have been flagged"


@pytest.mark.parametrize("pattern", ["(a|b)*c", "a+b+c", r"^\w+@\w+\.\w+$",
                                     "a{1,3}b", "[a-z]+[0-9]+", "(?:ab)+c"])
def test_the_checker_stays_quiet_on_the_safe_ones(pattern):
    assert analyse(pattern) == [], f"{pattern} should not have been flagged"


def test_the_checker_names_the_reason():
    findings = analyse("(a+)+b")
    assert findings[0].kind == "nested quantifier"
    assert "exponentially" in findings[0].detail


def test_an_ambiguous_alternation_is_its_own_finding():
    """`(a|a)*` has no nested quantifier — the two branches simply overlap, so
    the engine has a real choice at every character."""
    findings = analyse("(a|a)*b")
    assert [f.kind for f in findings] == ["ambiguous alternation"]


def test_a_disjoint_alternation_is_not_flagged():
    """`(a|b)*` looks the same and is harmless: the branches cannot both match
    the same character, so there is never a choice to un-make."""
    assert analyse("(a|b)*c") == []
