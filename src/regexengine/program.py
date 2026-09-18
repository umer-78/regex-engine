"""Compiling the syntax tree to a small instruction program.

Thompson's construction, in the instruction form Ken Thompson used in 1968: a
regular expression becomes a program for a tiny machine whose only interesting
instruction is `Split`, which runs two branches at once. There are no loops in
the compiler that can blow up and no backtracking in the machine, which is the
whole point.
"""

from __future__ import annotations

from dataclasses import dataclass

from .syntax import (
    Alternate,
    Anchor,
    Any,
    CharClass,
    Concat,
    Empty,
    Group,
    Literal,
    Node,
    RegexError,
    Repeat,
    parse,
)


@dataclass
class Instruction:
    op: str                     # char, class, any, split, jump, match, assert, save
    char: str = ""
    ranges: tuple[tuple[str, str], ...] = ()
    negated: bool = False
    x: int = 0
    y: int = 0
    slot: int = 0

    def consumes(self) -> bool:
        return self.op in ("char", "class", "any")

    def accepts(self, char: str) -> bool:
        if self.op == "char":
            return char == self.char
        if self.op == "any":
            return char != "\n"
        if self.op == "class":
            inside = any(low <= char <= high for low, high in self.ranges)
            return inside != self.negated
        return False


def holds(kind: str, position: int, length: int) -> bool:
    """Whether a zero-width assertion is satisfied here.

    Both automaton engines need this and it is a property of the instruction,
    not of either engine, so it lives with the instructions.
    """
    return (kind == "^" and position == 0) or (kind == "$" and position == length)


# The repetition limit exists because `a{1,1000}` is compiled by copying `a` a
# thousand times, which is what every engine does. Without a cap, `a{1,1000000}`
# is a denial of service against the *compiler* rather than the matcher.
MAX_REPEAT = 1000


class Compiler:
    def __init__(self) -> None:
        self.program: list[Instruction] = []

    def emit(self, instruction: Instruction) -> int:
        self.program.append(instruction)
        return len(self.program) - 1

    def compile(self, node: Node, groups: int) -> list[Instruction]:
        self.walk(node)
        self.emit(Instruction("match"))
        return self.program

    def walk(self, node: Node) -> None:
        if isinstance(node, Empty):
            return

        if isinstance(node, Literal):
            self.emit(Instruction("char", char=node.char))
            return

        if isinstance(node, Any):
            self.emit(Instruction("any"))
            return

        if isinstance(node, CharClass):
            self.emit(Instruction("class", ranges=tuple(node.ranges), negated=node.negated))
            return

        if isinstance(node, Anchor):
            self.emit(Instruction("assert", char=node.kind))
            return

        if isinstance(node, Group):
            if node.index is None:
                self.walk(node.node)
                return
            self.emit(Instruction("save", slot=2 * node.index))
            self.walk(node.node)
            self.emit(Instruction("save", slot=2 * node.index + 1))
            return

        if isinstance(node, Concat):
            for part in node.parts:
                self.walk(part)
            return

        if isinstance(node, Alternate):
            jumps = []
            for option in node.options[:-1]:
                split = self.emit(Instruction("split"))
                self.program[split].x = len(self.program)
                self.walk(option)
                jumps.append(self.emit(Instruction("jump")))
                self.program[split].y = len(self.program)
            self.walk(node.options[-1])
            for jump in jumps:
                self.program[jump].x = len(self.program)
            return

        if isinstance(node, Repeat):
            self.repeat(node)
            return

        raise TypeError(f"cannot compile {type(node).__name__}")

    def repeat(self, node: Repeat) -> None:
        if node.maximum is None:
            for _ in range(node.minimum):
                self.walk(node.node)
            self.star(node.node, node.greedy)
            return

        if node.maximum > MAX_REPEAT:
            raise RegexError(f"repetition count {node.maximum} is above the limit of {MAX_REPEAT}")

        for _ in range(node.minimum):
            self.walk(node.node)

        optional = node.maximum - node.minimum
        splits = []
        for _ in range(optional):
            split = self.emit(Instruction("split"))
            self.program[split].x = len(self.program)
            splits.append(split)
            self.walk(node.node)
        for split in splits:
            self.program[split].y = len(self.program)

    def star(self, node: Node, greedy: bool) -> None:
        split = self.emit(Instruction("split"))
        body = len(self.program)
        self.walk(node)
        jump = self.emit(Instruction("jump", x=split))
        after = len(self.program)

        self.program[jump].x = split
        if greedy:
            self.program[split].x, self.program[split].y = body, after
        else:
            self.program[split].x, self.program[split].y = after, body


def compile_pattern(pattern: str) -> tuple[list[Instruction], int]:
    node, groups = parse(pattern)
    return Compiler().compile(node, groups), groups


def disassemble(program: list[Instruction]) -> str:
    lines = []
    for address, instruction in enumerate(program):
        if instruction.op == "char":
            body = f"char {instruction.char!r}"
        elif instruction.op == "class":
            inside = "".join(f"{low}-{high}" for low, high in instruction.ranges)
            body = f"class {'^' if instruction.negated else ''}[{inside}]"
        elif instruction.op == "split":
            body = f"split {instruction.x}, {instruction.y}"
        elif instruction.op == "jump":
            body = f"jump {instruction.x}"
        elif instruction.op == "save":
            body = f"save {instruction.slot}"
        elif instruction.op == "assert":
            body = f"assert {instruction.char!r}"
        else:
            body = instruction.op
        lines.append(f"{address:>4}  {body}")
    return "\n".join(lines)
