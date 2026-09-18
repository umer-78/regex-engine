"""Parsing patterns, and refusing patterns that are not patterns."""

from __future__ import annotations

import pytest

from regexengine import RegexError, parse
from regexengine.syntax import (
    Alternate,
    Anchor,
    Any,
    Concat,
    Empty,
    Group,
    Literal,
    Repeat,
)


def tree(pattern: str):
    return parse(pattern)[0]


# -- precedence --------------------------------------------------------------

def test_alternation_binds_loosest():
    """`ab|cd` is `(ab)|(cd)`, not `a(b|c)d`."""
    node = tree("ab|cd")
    assert isinstance(node, Alternate)
    assert all(isinstance(option, Concat) for option in node.options)


def test_repetition_binds_tightest():
    """`ab*` repeats the b, not the ab."""
    node = tree("ab*")
    assert isinstance(node, Concat)
    assert isinstance(node.parts[1], Repeat)
    assert node.parts[1].node == Literal("b")


def test_a_group_changes_what_is_repeated():
    node = tree("(ab)*")
    assert isinstance(node, Repeat)
    assert isinstance(node.node, Group)


def test_alternation_inside_a_group():
    node = tree("a(b|c)d")
    assert isinstance(node.parts[1].node, Alternate)


def test_an_empty_alternative_is_allowed():
    """`(|a)` is a legitimate way to write `a?`."""
    node = tree("(|a)")
    assert isinstance(node.node.options[0], Empty)


# -- repetition --------------------------------------------------------------

@pytest.mark.parametrize(("pattern", "minimum", "maximum"), [
    ("a*", 0, None), ("a+", 1, None), ("a?", 0, 1),
    ("a{3}", 3, 3), ("a{2,}", 2, None), ("a{2,5}", 2, 5), ("a{0,1}", 0, 1),
])
def test_repetition_bounds(pattern, minimum, maximum):
    node = tree(pattern)
    assert (node.minimum, node.maximum) == (minimum, maximum)


def test_lazy_repetition_is_marked():
    assert tree("a*?").greedy is False
    assert tree("a*").greedy is True


def test_a_brace_that_is_not_a_count_is_a_literal():
    """`a{` and `a{x}` are braces, not malformed counts — which is what every
    other engine does, and refusing them would break patterns that work."""
    node = tree("a{x}")
    assert isinstance(node, Concat)
    assert node.parts[1] == Literal("{")


def test_a_backwards_count_is_rejected():
    with pytest.raises(RegexError, match="counts backwards"):
        parse("a{5,2}")


def test_a_repeat_of_a_repeat_is_rejected():
    """`(a*)*` — the compiler would loop on the empty match. Rejecting the
    obvious accident is not a defence against nesting in general; `(a+)+` still
    parses, and still explodes on a backtracking engine."""
    with pytest.raises(RegexError, match="nothing to repeat"):
        parse("a**")
    parse("(a+)+")            # this one is legal, and is the ReDoS example


def test_a_leading_quantifier_is_rejected():
    for pattern in ("*a", "+a", "?a"):
        with pytest.raises(RegexError, match="nothing to repeat"):
            parse(pattern)


# -- character classes -------------------------------------------------------

def test_a_class_of_single_characters():
    node = tree("[abc]")
    assert node.ranges == [("a", "a"), ("b", "b"), ("c", "c")]
    assert all(node.matches(char) for char in "abc")
    assert not node.matches("d")


def test_a_range():
    node = tree("[a-f]")
    assert node.matches("c") and not node.matches("g")


def test_a_negated_class():
    node = tree("[^0-9]")
    assert node.negated
    assert node.matches("a") and not node.matches("5")


def test_a_literal_dash_at_the_end():
    """`[a-]` is `a` or `-`, not a broken range."""
    node = tree("[a-]")
    assert node.matches("a") and node.matches("-")


def test_a_closing_bracket_first_is_a_literal():
    node = tree("[]a]")
    assert node.matches("]") and node.matches("a")


def test_a_backwards_range_is_rejected():
    with pytest.raises(RegexError, match="counts backwards"):
        parse("[z-a]")


def test_an_unterminated_class_is_rejected():
    with pytest.raises(RegexError, match="unterminated character class"):
        parse("[abc")


@pytest.mark.parametrize(("escape", "inside", "outside"), [
    (r"\d", "5", "a"), (r"\w", "a", "-"), (r"\s", " ", "a"),
    (r"\D", "a", "5"), (r"\W", "-", "a"), (r"\S", "a", " "),
])
def test_shorthand_classes(escape, inside, outside):
    node = tree(escape)
    assert node.matches(inside)
    assert not node.matches(outside)


def test_an_escaped_metacharacter_is_a_literal():
    assert tree(r"\.") == Literal(".")
    assert tree(r"\*") == Literal("*")


def test_control_escapes():
    assert tree(r"\n") == Literal("\n")
    assert tree(r"\t") == Literal("\t")


# -- groups ------------------------------------------------------------------

def test_capture_groups_are_numbered_in_source_order():
    node, count = parse("(a)(b)(c)")
    assert count == 3
    assert [part.index for part in node.parts] == [1, 2, 3]


def test_nested_groups_number_by_opening_parenthesis():
    node, count = parse("((a)(b))")
    assert count == 3
    assert node.index == 1
    assert [part.index for part in node.node.parts] == [2, 3]


def test_a_non_capturing_group_takes_no_number():
    node, count = parse("(?:a)(b)")
    assert count == 1
    assert node.parts[0].index is None
    assert node.parts[1].index == 1


def test_an_unclosed_group_is_rejected():
    with pytest.raises(RegexError, match=r"expected '\)'"):
        parse("(ab")


@pytest.mark.parametrize("pattern", ["ab)", "(a))b", ")"])
def test_a_stray_closing_parenthesis_is_rejected(pattern):
    """Caught by the leftover check in parse(), not by a branch in atom():
    concatenation stops at ')', so an atom never sees one."""
    with pytest.raises(RegexError, match=r"unexpected '\)'"):
        parse(pattern)


# -- anchors and errors ------------------------------------------------------

def test_anchors():
    node = tree("^a$")
    assert isinstance(node.parts[0], Anchor) and node.parts[0].kind == "^"
    assert isinstance(node.parts[2], Anchor) and node.parts[2].kind == "$"


def test_dot_is_any():
    assert isinstance(tree("."), Any)


def test_a_trailing_backslash_is_rejected():
    with pytest.raises(RegexError, match="ends with a backslash"):
        parse("a\\")


def test_an_empty_pattern_is_empty_not_an_error():
    assert isinstance(tree(""), Empty)


def test_an_error_points_at_the_offending_character():
    with pytest.raises(RegexError) as error:
        parse("ab[cd")
    assert error.value.position == 2
    assert "^" in str(error.value)
