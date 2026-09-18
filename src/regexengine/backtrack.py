"""The backtracking matcher — the one almost everybody writes, and the one
almost every language ships.

It is simple, it supports capture groups and backreferences naturally, and on a
pattern like `(a+)+b` it takes exponential time. That is not a bug in this
implementation: it is what backtracking *is*, and it is the mechanism behind
every ReDoS advisory. `steps` counts the work so the shape of the explosion can
be measured rather than described.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    Repeat,
    parse,
)


@dataclass
class Match:
    start: int
    end: int
    text: str
    groups: dict[int, tuple[int, int]] = field(default_factory=dict)

    @property
    def matched(self) -> str:
        return self.text[self.start:self.end]

    def group(self, index: int = 0) -> str | None:
        if index == 0:
            return self.matched
        span = self.groups.get(index)
        return self.text[span[0]:span[1]] if span else None


class StepLimit(RuntimeError):
    """Raised when a match exceeds the step budget.

    A budget is the only defence a backtracking engine has. Every production
    regex library that has been bitten by ReDoS has ended up adding one, and a
    library that offers no limit at all is offering the caller a denial of
    service with a nice API.
    """

    def __init__(self, steps: int):
        super().__init__(f"gave up after {steps:,} steps")
        self.steps = steps


class Backtracking:
    def __init__(self, pattern: str, *, limit: int | None = None):
        self.pattern = pattern
        self.node, self.group_count = parse(pattern)
        self.limit = limit
        self.steps = 0

    # -- entry ------------------------------------------------------------

    def search(self, text: str) -> Match | None:
        """Try every starting offset, which is what makes an unanchored search
        O(n) times whatever one attempt costs."""
        self.steps = 0
        for start in range(len(text) + 1):
            groups: dict[int, tuple[int, int]] = {}
            end = self.match_node(self.node, text, start, groups, lambda position, _g: position)
            if end is not None:
                return Match(start, end, text, groups)
        return None

    def matches(self, text: str) -> bool:
        return self.search(text) is not None

    def fullmatch(self, text: str) -> Match | None:
        self.steps = 0
        groups: dict[int, tuple[int, int]] = {}
        end = self.match_node(self.node, text, 0, groups,
                              lambda position, _g: position if position == len(text) else None)
        return Match(0, end, text, groups) if end is not None else None

    # -- the walk ---------------------------------------------------------

    def tick(self) -> None:
        self.steps += 1
        if self.limit is not None and self.steps > self.limit:
            raise StepLimit(self.steps)

    def match_node(self, node: Node, text: str, position: int,
                   groups: dict[int, tuple[int, int]], cont) -> int | None:
        """Continuation-passing, because a regex is not a sequence of
        independent decisions: whether `a*` should stop here depends on whether
        everything *after* it can then match. `cont` is "the rest of the
        pattern", and handing it down is what lets a choice be un-made.
        """
        self.tick()

        if isinstance(node, Empty):
            return cont(position, groups)

        if isinstance(node, Literal):
            if position < len(text) and text[position] == node.char:
                return cont(position + 1, groups)
            return None

        if isinstance(node, Any):
            if position < len(text) and text[position] != "\n":
                return cont(position + 1, groups)
            return None

        if isinstance(node, CharClass):
            if position < len(text) and node.matches(text[position]):
                return cont(position + 1, groups)
            return None

        if isinstance(node, Anchor):
            if node.kind == "^" and position == 0:
                return cont(position, groups)
            if node.kind == "$" and position == len(text):
                return cont(position, groups)
            return None

        if isinstance(node, Group):
            def close(end: int, inner_groups, node=node, start=position):
                if node.index is not None:
                    inner_groups[node.index] = (start, end)
                return cont(end, inner_groups)
            return self.match_node(node.node, text, position, groups, close)

        if isinstance(node, Concat):
            return self.match_sequence(node.parts, text, position, groups, cont)

        if isinstance(node, Alternate):
            for option in node.options:
                result = self.match_node(option, text, position, groups, cont)
                if result is not None:
                    return result
            return None

        if isinstance(node, Repeat):
            return self.match_repeat(node, text, position, groups, cont, 0)

        raise TypeError(f"cannot match {type(node).__name__}")

    def match_sequence(self, parts: list[Node], text: str, position: int,
                       groups: dict[int, tuple[int, int]], cont) -> int | None:
        if not parts:
            return cont(position, groups)
        head, rest = parts[0], parts[1:]
        return self.match_node(
            head, text, position, groups,
            lambda next_position, next_groups: self.match_sequence(
                rest, text, next_position, next_groups, cont))

    def match_repeat(self, node: Repeat, text: str, position: int,
                     groups: dict[int, tuple[int, int]], cont, done: int) -> int | None:
        """Where the time goes.

        Below the minimum there is no choice. Above it there are two — take
        another repetition, or stop — and the engine tries both. With one
        repeat that is linear. With a repeat inside a repeat, the number of ways
        to divide the input between the two levels is exponential in the input
        length, and a pattern that fails only at the very end makes the engine
        try all of them.
        """
        self.tick()

        if node.maximum is not None and done >= node.maximum:
            return cont(position, groups)

        def take_more(next_position: int, next_groups, done=done, position=position):
            if next_position == position and done >= node.minimum:
                # An empty repetition would loop forever. `(a*)*` against "" is
                # the smallest case.
                return None
            return self.match_repeat(node, text, next_position, next_groups, cont, done + 1)

        if done < node.minimum:
            return self.match_node(node.node, text, position, groups, take_more)

        if node.greedy:
            result = self.match_node(node.node, text, position, groups, take_more)
            if result is not None:
                return result
            return cont(position, groups)

        result = cont(position, groups)
        if result is not None:
            return result
        return self.match_node(node.node, text, position, groups, take_more)


def search(pattern: str, text: str, *, limit: int | None = None) -> Match | None:
    return Backtracking(pattern, limit=limit).search(text)
