"""Simulating the program with every thread at once.

The backtracking engine tries one path through the automaton, and when it fails
it goes back and tries another. This one advances *all* live positions through
the input together, one character at a time. Because the set of live positions
can never be larger than the program, the work is bounded by
O(len(text) x len(program)) whatever the pattern looks like — and the patterns
that take a backtracking engine exponential time take this one no longer than
any other pattern of the same size.

The price is capture groups. Tracking which thread captured what needs a slot
array carried per thread, which is what `Pike` below does and what makes it
slower than the plain membership test in `matches`. Backreferences are not
supported at all, and cannot be: they make the language non-regular, which is
why every engine that offers them is a backtracking engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .program import compile_pattern, holds


@dataclass
class Trace:
    """What the simulation did, for comparing against the backtracking engine."""

    steps: int = 0
    threads_peak: int = 0
    characters: int = 0


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


class Thompson:
    def __init__(self, pattern: str):
        self.pattern = pattern
        self.program, self.group_count = compile_pattern(pattern)
        self.trace = Trace()

    # -- membership -------------------------------------------------------

    def matches(self, text: str) -> bool:
        """Does the pattern match anywhere? No captures, so no slot copying."""
        self.trace = Trace(characters=len(text))
        program = self.program

        current: set[int] = set()
        self.add(current, 0, text, 0)

        for position, char in enumerate(text):
            # A fresh thread joins at every position, so an unanchored search
            # can still start after everything else has died.
            self.trace.threads_peak = max(self.trace.threads_peak, len(current))

            following: set[int] = set()
            for address in current:
                self.trace.steps += 1
                instruction = program[address]
                if instruction.op == "match":
                    return True
                if instruction.consumes() and instruction.accepts(char):
                    self.add(following, address + 1, text, position + 1)
            self.add(following, 0, text, position + 1)
            current = following

        return any(program[address].op == "match" for address in current)

    def add(self, threads: set[int], address: int, text: str, position: int) -> None:
        """Follow every non-consuming instruction until a real one is reached.

        The `in threads` check is the load-bearing line of the whole engine: it
        is what stops two paths that have converged on the same program address
        from being explored twice, and therefore what turns the exponential
        number of *paths* into a linear number of *positions*.
        """
        if address in threads:
            return
        threads.add(address)
        self.trace.steps += 1

        instruction = self.program[address]
        if instruction.op == "jump":
            self.add(threads, instruction.x, text, position)
        elif instruction.op == "split":
            self.add(threads, instruction.x, text, position)
            self.add(threads, instruction.y, text, position)
        elif instruction.op == "save" or instruction.op == "assert" and holds(instruction.char, position, len(text)):
            self.add(threads, address + 1, text, position)


class Pike:
    """The same simulation, carrying capture slots.

    Threads are kept in priority order rather than a set, because leftmost-first
    semantics — which alternative wins, how greedy a star is — is decided by the
    order threads were added, and a set has no order.
    """

    def __init__(self, pattern: str):
        self.pattern = pattern
        self.program, self.group_count = compile_pattern(pattern)
        self.slots = 2 * (self.group_count + 1)
        self.trace = Trace()

    def search(self, text: str) -> Match | None:
        self.trace = Trace(characters=len(text))
        matched: list[int] | None = None

        current: list[tuple[int, list[int]]] = []
        seen: set[int] = set()
        self.add(current, seen, 0, [-1] * self.slots, text, 0)

        for position in range(len(text) + 1):
            self.trace.threads_peak = max(self.trace.threads_peak, len(current))
            following: list[tuple[int, list[int]]] = []
            following_seen: set[int] = set()

            for address, slots in current:
                self.trace.steps += 1
                instruction = self.program[address]

                if instruction.op == "match":
                    matched = slots
                    # Threads after this one are lower priority, so once one has
                    # matched the rest cannot win. Cutting them is what makes
                    # leftmost-first mean something.
                    break

                if position < len(text) and instruction.consumes() \
                        and instruction.accepts(text[position]):
                    slots = list(slots)
                    self.add(following, following_seen, address + 1, slots, text, position + 1)

            if matched is None and position < len(text):
                start = [-1] * self.slots
                start[0] = position + 1
                self.add(following, following_seen, 0, start, text, position + 1)

            current = following
            if not current:
                break

        if matched is None:
            return None

        start = max(matched[0], 0)
        end = matched[1] if matched[1] >= 0 else start
        groups = {
            index: (matched[2 * index], matched[2 * index + 1])
            for index in range(1, self.group_count + 1)
            if matched[2 * index] >= 0 and matched[2 * index + 1] >= 0
        }
        return Match(start, end, text, groups)

    def add(self, threads: list[tuple[int, list[int]]], seen: set[int], address: int,
            slots: list[int], text: str, position: int) -> None:
        if address in seen:
            return
        seen.add(address)
        self.trace.steps += 1

        instruction = self.program[address]
        if instruction.op == "jump":
            self.add(threads, seen, instruction.x, slots, text, position)
        elif instruction.op == "split":
            self.add(threads, seen, instruction.x, list(slots), text, position)
            self.add(threads, seen, instruction.y, list(slots), text, position)
        elif instruction.op == "save":
            slots = list(slots)
            slots[instruction.slot] = position
            self.add(threads, seen, address + 1, slots, text, position)
        elif instruction.op == "assert" and holds(instruction.char, position, len(text)):
            self.add(threads, seen, address + 1, slots, text, position)
        elif instruction.op == "match":
            slots = list(slots)
            slots[1] = position
            slots[0] = max(slots[0], 0)
            threads.append((address, slots))
        else:
            threads.append((address, slots))


def matches(pattern: str, text: str) -> bool:
    return Thompson(pattern).matches(text)


def search(pattern: str, text: str) -> Match | None:
    return Pike(pattern).search(text)
