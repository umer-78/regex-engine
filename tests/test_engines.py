"""Every engine must give the same answer, and the same answer as Python's re."""

from __future__ import annotations

import random
import re as stdlib

import pytest

from regexengine import Backtracking, LazyDFA, Pike, StepLimit, Thompson

# Patterns and subjects chosen to cover each construct and each boundary. Every
# one is also run through Python's own re, which is the reference.
CASES = [
    ("", ""), ("", "abc"),
    ("a", "a"), ("a", "b"), ("a", ""), ("a", "bbbab"),
    ("abc", "xxabcxx"), ("abc", "xxabxx"),
    ("a|b", "b"), ("a|b", "c"), ("cat|dog", "hotdog"),
    ("a*", ""), ("a*", "aaa"), ("a*b", "aaab"), ("a*b", "b"), ("a*b", "aaa"),
    ("a+", ""), ("a+", "aaa"), ("a+b", "b"),
    ("a?b", "b"), ("a?b", "ab"),
    ("a{2}", "a"), ("a{2}", "aa"), ("a{2,3}", "aaaa"), ("a{2,}", "aaaaa"),
    (".", ""), (".", "x"), (".", "\n"), ("a.c", "abc"), ("a.c", "a\nc"),
    ("[abc]", "b"), ("[abc]", "d"), ("[a-z]+", "hello"), ("[^a-z]", "A"),
    ("[0-9]{3}", "abc123"),
    ("^abc", "abc"), ("^abc", "xabc"), ("abc$", "xabc"), ("abc$", "abcx"),
    ("^$", ""), ("^$", "a"), ("^a*$", "aaa"),
    ("(a)(b)", "ab"), ("(ab)+", "ababab"), ("(a|b)*c", "abababc"),
    ("(?:ab)+", "abab"),
    (r"\d+", "abc123"), (r"\w+@\w+", "mail me at user@example"),
    (r"\d+\.\d+", "pi is 3.14159"), (r"\s+", "a b"),
    (r"a\*b", "a*b"), (r"\.", "."),
    ("(a+)+b", "aaaaaaaaab"), ("(a+)+b", "aaaaaaaaa"),
    ("a(b|c)*d", "abcbcbcd"), ("a(b|c)*d", "abcbcbce"),
    ("colou?r", "color"), ("colou?r", "colour"),
    ("^[a-z]+[0-9]{2,4}$", "abc1234"), ("^[a-z]+[0-9]{2,4}$", "abc12345"),
]


@pytest.mark.parametrize(("pattern", "text"), CASES)
def test_every_engine_agrees_with_python(pattern, text):
    reference = stdlib.search(pattern, text) is not None

    assert Thompson(pattern).matches(text) is reference, "thompson"
    assert LazyDFA(pattern).matches(text) is reference, "lazy dfa"
    assert (Pike(pattern).search(text) is not None) is reference, "pike"

    backtracking = Backtracking(pattern, limit=5_000_000)
    assert backtracking.matches(text) is reference, "backtracking"


def test_the_engines_agree_on_random_patterns():
    """Generated patterns, not hand-picked ones. Hand-picked cases test what the
    author already thought of, which is the same set of things the implementation
    already handles."""
    rng = random.Random(7)
    atoms = ["a", "b", "c", ".", "[ab]", "[^a]", r"\d", r"\w"]
    disagreements = []

    for _ in range(600):
        pattern = ""
        for _ in range(rng.randint(1, 5)):
            piece = rng.choice(atoms)
            if rng.random() < 0.3:
                piece = "(" + piece + rng.choice(["", "|b", "|c"]) + ")"
            piece += rng.choice(["", "", "*", "+", "?", "{1,2}"])
            pattern += piece
        if rng.random() < 0.2:
            pattern = "^" + pattern
        if rng.random() < 0.2:
            pattern += "$"

        text = "".join(rng.choice("abc123 ") for _ in range(rng.randint(0, 8)))

        try:
            reference = stdlib.search(pattern, text) is not None
        except stdlib.error:
            continue

        for name, answer in (
            ("thompson", Thompson(pattern).matches(text)),
            ("dfa", LazyDFA(pattern).matches(text)),
            ("pike", Pike(pattern).search(text) is not None),
            ("backtracking", Backtracking(pattern, limit=2_000_000).matches(text)),
        ):
            if answer is not reference:
                disagreements.append((name, pattern, text, answer, reference))

    assert not disagreements, disagreements[:5]


# -- captures ----------------------------------------------------------------

CAPTURE_CASES = [
    ("(a)(b)", "ab"),
    ("(foo)(bar)", "xfoobary"),
    ("(a+)(b+)", "aaabbb"),
    (r"(\w+)@(\w+)", "user@example"),
    ("(a|b)(c|d)", "bd"),
    ("(ab)+", "ababab"),
    ("(a)?b", "b"),
    ("(a)?b", "ab"),
    (r"(\d+)\.(\d+)", "pi is 3.14"),
]


@pytest.mark.parametrize(("pattern", "text"), CAPTURE_CASES)
def test_captures_match_python(pattern, text):
    reference = stdlib.search(pattern, text)
    assert reference is not None

    for engine in (Backtracking(pattern), Pike(pattern)):
        found = engine.search(text)
        assert found is not None
        assert found.matched == reference.group(0), type(engine).__name__
        for index in range(1, engine.group_count + 1):
            assert found.group(index) == reference.group(index), \
                f"{type(engine).__name__} group {index}"


def test_a_group_that_did_not_participate_is_none():
    for engine in (Backtracking("(a)?b"), Pike("(a)?b")):
        found = engine.search("b")
        assert found is not None
        assert found.group(1) is None


def test_match_positions():
    found = Pike("b+").search("aabbbcc")
    assert (found.start, found.end) == (2, 5)
    assert found.matched == "bbb"


# -- leftmost-first ----------------------------------------------------------

def test_the_leftmost_match_wins():
    assert Pike("a|ab").search("xxab").start == 2
    assert Backtracking("a|ab").search("xxab").start == 2


def test_alternation_is_first_not_longest():
    """`a|ab` against "ab" gives "a", because the first alternative that works
    wins. A POSIX engine would return "ab"; nearly nothing is a POSIX engine,
    and Python is not."""
    assert stdlib.search("a|ab", "ab").group(0) == "a"
    assert Pike("a|ab").search("ab").matched == "a"
    assert Backtracking("a|ab").search("ab").matched == "a"


def test_star_is_greedy():
    assert Pike("a.*b").search("axbxb").matched == "axbxb"
    assert Backtracking("a.*b").search("axbxb").matched == "axbxb"


def test_lazy_star_is_not():
    assert stdlib.search("a.*?b", "axbxb").group(0) == "axb"
    assert Backtracking("a.*?b").search("axbxb").matched == "axb"


def test_fullmatch_requires_the_whole_string():
    engine = Backtracking("a+")
    assert engine.fullmatch("aaa") is not None
    assert engine.fullmatch("aaab") is None


# -- the step budget ---------------------------------------------------------

def test_the_backtracking_engine_can_be_capped():
    with pytest.raises(StepLimit) as error:
        Backtracking("(a+)+b", limit=10_000).matches("a" * 30)
    assert error.value.steps > 10_000


def test_the_automaton_engines_need_no_cap():
    """The same input, the same pattern, no budget and no trouble."""
    assert Thompson("(a+)+b").matches("a" * 200) is False
    assert LazyDFA("(a+)+b").matches("a" * 200) is False
