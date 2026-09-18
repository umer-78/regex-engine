"""Compiling to the instruction program."""

from __future__ import annotations

import pytest

from regexengine import RegexError, compile_pattern, disassemble
from regexengine.program import MAX_REPEAT


def ops(pattern: str) -> list[str]:
    program, _ = compile_pattern(pattern)
    return [instruction.op for instruction in program]


def test_a_literal_compiles_to_one_instruction_and_a_match():
    assert ops("a") == ["char", "match"]


def test_concatenation_is_just_sequence():
    assert ops("abc") == ["char", "char", "char", "match"]


def test_a_star_is_a_split_and_a_jump():
    """Thompson's construction: one split to choose between entering the loop
    and leaving it, one jump back. No recursion, no backtracking."""
    assert ops("a*") == ["split", "char", "jump", "match"]


def test_a_plus_runs_the_body_once_first():
    assert ops("a+") == ["char", "split", "char", "jump", "match"]


def test_a_question_mark_is_a_split_with_no_jump_back():
    assert ops("a?") == ["split", "char", "match"]


def test_alternation_is_a_split_and_a_jump_past():
    assert ops("a|b") == ["split", "char", "jump", "char", "match"]


def test_a_counted_repeat_is_copies():
    """`a{3}` is `aaa`, which is what every engine does — and the reason a huge
    count is a denial of service against the compiler rather than the matcher."""
    assert ops("a{3}") == ["char", "char", "char", "match"]
    assert ops("a{1,3}").count("char") == 3


def test_a_huge_repeat_count_is_refused():
    with pytest.raises(RegexError, match="above the limit"):
        compile_pattern(f"a{{1,{MAX_REPEAT + 1}}}")


def test_a_repeat_at_the_limit_is_allowed():
    program, _ = compile_pattern(f"a{{1,{MAX_REPEAT}}}")
    assert len(program) > MAX_REPEAT


def test_capture_groups_become_save_instructions():
    assert ops("(a)") == ["save", "char", "save", "match"]


def test_a_non_capturing_group_emits_no_saves():
    assert "save" not in ops("(?:a)")


def test_save_slots_are_paired():
    program, count = compile_pattern("(a)(b)")
    slots = [i.slot for i in program if i.op == "save"]
    assert slots == [2, 3, 4, 5]
    assert count == 2


def test_lazy_and_greedy_differ_only_in_the_split_order():
    greedy, _ = compile_pattern("a*")
    lazy, _ = compile_pattern("a*?")
    assert [i.op for i in greedy] == [i.op for i in lazy]
    assert (greedy[0].x, greedy[0].y) == (lazy[0].y, lazy[0].x)


def test_every_jump_and_split_points_inside_the_program():
    for pattern in ["a", "a*", "(a|b)*c", "a{2,4}", "((a)(b))+", r"^\d+\.\d+$"]:
        program, _ = compile_pattern(pattern)
        for instruction in program:
            if instruction.op in ("jump", "split"):
                assert 0 <= instruction.x < len(program), pattern
            if instruction.op == "split":
                assert 0 <= instruction.y < len(program), pattern


def test_the_program_always_ends_in_match():
    for pattern in ["", "a", "a*", "(a|b)+"]:
        program, _ = compile_pattern(pattern)
        assert program[-1].op == "match"


def test_disassembly_is_readable():
    text = disassemble(compile_pattern("a(b|c)*d")[0])
    assert "char 'a'" in text
    assert "split" in text and "jump" in text and "match" in text
    assert len(text.splitlines()) == len(compile_pattern("a(b|c)*d")[0])
