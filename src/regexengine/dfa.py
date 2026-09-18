"""A lazy DFA over the same program.

The Thompson simulation recomputes the set of live program addresses at every
character. But that set is a function of the previous set and the character, so
it can be cached: each distinct set becomes one DFA state, and matching becomes
a table lookup per character with no set arithmetic at all.

The catch is the one every textbook mentions and few measure: the number of
distinct sets can be exponential in the size of the pattern. `.*a.{k}` is the
standard example — the automaton must remember which of the last k characters
was an `a`, which is 2^k states. Building the table *lazily*, only for the
states the input actually visits, bounds it by the input rather than the
pattern; `states_visited` and `states_built` are reported so the difference can
be seen rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .program import compile_pattern, holds


@dataclass
class Trace:
    steps: int = 0
    states_built: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    characters: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total else 0.0


@dataclass
class State:
    addresses: frozenset[int]
    accepting: bool
    # Keyed by (character, context) rather than by character alone. `^` and `$`
    # make the transition function depend on *where* in the input we are, so a
    # transition worked out in the middle of the string is not the transition to
    # take at its end. Caching on the character alone reuses the wrong one, and
    # every pattern ending in `$` then fails to match — which is exactly what the
    # random-pattern test caught.
    next: dict[tuple[str, int], State] = field(default_factory=dict)


def context(position: int, length: int) -> int:
    """Which zero-width assertions hold at this position.

    Part of the cache key, because `^` and `$` make the transition function
    depend on where in the input we are.
    """
    return (1 if position == 0 else 0) | (2 if position == length else 0)


class LazyDFA:
    def __init__(self, pattern: str, *, cache_limit: int = 10_000):
        self.pattern = pattern
        self.program, self.group_count = compile_pattern(pattern)
        self.cache_limit = cache_limit
        self.cache: dict[tuple[frozenset[int], int], State] = {}
        self.trace = Trace()

    # -- construction -----------------------------------------------------

    def closure(self, addresses: set[int], position: int, length: int) -> frozenset[int]:
        """Follow every non-consuming instruction, as the NFA simulation does."""
        out: set[int] = set()
        stack = list(addresses)
        while stack:
            address = stack.pop()
            if address in out:
                continue
            out.add(address)
            self.trace.steps += 1

            instruction = self.program[address]
            if instruction.op == "jump":
                stack.append(instruction.x)
            elif instruction.op == "split":
                stack.append(instruction.x)
                stack.append(instruction.y)
            elif instruction.op == "save" or instruction.op == "assert" and holds(instruction.char, position, length):
                stack.append(address + 1)
        return frozenset(out)

    def state_for(self, addresses: frozenset[int], where: int) -> State:
        key = (addresses, where)
        existing = self.cache.get(key)
        if existing is not None:
            self.trace.cache_hits += 1
            return existing

        self.trace.cache_misses += 1
        if len(self.cache) >= self.cache_limit:
            # Dropping the table and starting again keeps the memory bounded at
            # the cost of rebuilding. A DFA that grows without limit turns a
            # pathological *pattern* into a memory exhaustion, which is the same
            # denial of service backtracking gives you in time.
            self.cache.clear()

        state = State(addresses, any(self.program[a].op == "match" for a in addresses))
        self.cache[key] = state
        self.trace.states_built += 1
        return state

    # -- matching ---------------------------------------------------------

    def matches(self, text: str) -> bool:
        self.cache.clear()
        self.trace = Trace(characters=len(text))

        length = len(text)
        state = self.state_for(self.closure({0}, 0, length), context(0, length))
        if state.accepting:
            return True

        for position, char in enumerate(text):
            where = context(position + 1, length)
            following = state.next.get((char, where))
            if following is None:
                addresses: set[int] = set()
                for address in state.addresses:
                    instruction = self.program[address]
                    if instruction.consumes() and instruction.accepts(char):
                        addresses.add(address + 1)
                addresses.add(0)          # an unanchored search may start here
                following = self.state_for(self.closure(addresses, position + 1, length), where)
                state.next[(char, where)] = following
            else:
                self.trace.cache_hits += 1

            state = following
            self.trace.steps += 1
            if state.accepting:
                return True

        return state.accepting


def matches(pattern: str, text: str) -> bool:
    return LazyDFA(pattern).matches(text)
