"""The regular expression parser: pattern text to a syntax tree."""

from __future__ import annotations

from dataclasses import dataclass, field


class RegexError(ValueError):
    """A pattern that is not a pattern. Carries the offset that broke it."""

    def __init__(self, message: str, position: int = 0, pattern: str = ""):
        super().__init__(message)
        self.message = message
        self.position = position
        self.pattern = pattern

    def __str__(self) -> str:
        if not self.pattern:
            return f"{self.message} (at position {self.position})"
        pointer = " " * self.position + "^"
        return f"{self.message}\n  {self.pattern}\n  {pointer}"


class Node:
    pass


@dataclass
class Empty(Node):
    """Matches the empty string. What `(|a)` has on its left."""


@dataclass
class Literal(Node):
    char: str


@dataclass
class Any(Node):
    """`.` — any character except a newline, as everyone expects."""


@dataclass
class CharClass(Node):
    """`[abc]`, `[a-z]`, `[^0-9]`, and the `\\d` `\\w` `\\s` shorthands."""

    ranges: list[tuple[str, str]] = field(default_factory=list)
    negated: bool = False

    def matches(self, char: str) -> bool:
        inside = any(low <= char <= high for low, high in self.ranges)
        return inside != self.negated


@dataclass
class Concat(Node):
    parts: list[Node]


@dataclass
class Alternate(Node):
    options: list[Node]


@dataclass
class Repeat(Node):
    """`a*`, `a+`, `a?` and `a{n,m}`, all one node.

    `greedy` only changes which match a backtracking engine finds first; it
    makes no difference to *whether* the pattern matches, which is why the
    automaton engines can ignore it entirely.
    """

    node: Node
    minimum: int = 0
    maximum: int | None = None       # None means unbounded
    greedy: bool = True


@dataclass
class Group(Node):
    node: Node
    index: int | None = None         # None for a non-capturing group


@dataclass
class Anchor(Node):
    kind: str                        # "^" or "$"


ESCAPES = {
    "d": [("0", "9")],
    "w": [("a", "z"), ("A", "Z"), ("0", "9"), ("_", "_")],
    "s": [(" ", " "), ("\t", "\t"), ("\n", "\n"), ("\r", "\r"), ("\f", "\f"), ("\v", "\v")],
}
CONTROL = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v", "0": "\0"}


class Parser:
    """Recursive descent over the three levels of regex precedence.

    Alternation binds loosest, then concatenation, then repetition — so `ab|c*`
    is `(ab)|(c*)`. Three functions, one per level, which is the shape the
    grammar has and therefore the shape the parser should have.
    """

    def __init__(self, pattern: str):
        self.pattern = pattern
        self.position = 0
        self.groups = 0

    # -- helpers ----------------------------------------------------------

    @property
    def at_end(self) -> bool:
        return self.position >= len(self.pattern)

    def peek(self) -> str:
        return self.pattern[self.position] if not self.at_end else ""

    def advance(self) -> str:
        char = self.pattern[self.position]
        self.position += 1
        return char

    def expect(self, char: str) -> None:
        if self.at_end or self.pattern[self.position] != char:
            raise RegexError(f"expected {char!r}", self.position, self.pattern)
        self.position += 1

    def fail(self, message: str, position: int | None = None):
        raise RegexError(message, self.position if position is None else position, self.pattern)

    # -- grammar ----------------------------------------------------------

    def parse(self) -> tuple[Node, int]:
        node = self.alternation()
        if not self.at_end:
            self.fail(f"unexpected {self.peek()!r}")
        return node, self.groups

    def alternation(self) -> Node:
        options = [self.concatenation()]
        while self.peek() == "|":
            self.advance()
            options.append(self.concatenation())
        return options[0] if len(options) == 1 else Alternate(options)

    def concatenation(self) -> Node:
        parts: list[Node] = []
        while not self.at_end and self.peek() not in "|)":
            parts.append(self.repetition())
        if not parts:
            return Empty()
        return parts[0] if len(parts) == 1 else Concat(parts)

    def repetition(self) -> Node:
        node = self.atom()

        while not self.at_end and self.peek() in "*+?{":
            start = self.position
            if self.peek() == "{":
                bounds = self.counted()
                if bounds is None:      # a lone '{' is a literal brace
                    break
                minimum, maximum = bounds
            else:
                symbol = self.advance()
                minimum, maximum = {"*": (0, None), "+": (1, None), "?": (0, 1)}[symbol]

            if isinstance(node, Repeat) and node.minimum == 0:
                # `(a*)*` and friends. Nesting them is what makes a backtracking
                # engine explode, and collapsing the trivial case here is not a
                # fix — it just stops the most obvious accident.
                self.fail("nothing to repeat", start)

            greedy = True
            if self.peek() == "?":
                self.advance()
                greedy = False
            node = Repeat(node, minimum, maximum, greedy)

        return node

    def counted(self) -> tuple[int, int | None] | None:
        """`{n}`, `{n,}`, `{n,m}` — or None if this brace is just a brace."""
        start = self.position
        self.advance()                                   # {

        digits = ""
        while self.peek().isdigit():
            digits += self.advance()
        if not digits:
            self.position = start
            return None

        minimum = int(digits)
        maximum: int | None = minimum
        if self.peek() == ",":
            self.advance()
            digits = ""
            while self.peek().isdigit():
                digits += self.advance()
            maximum = int(digits) if digits else None

        if self.peek() != "}":
            self.position = start
            return None
        self.advance()

        if maximum is not None and maximum < minimum:
            self.fail(f"{{{minimum},{maximum}}} counts backwards", start)
        return minimum, maximum

    def atom(self) -> Node:
        if self.at_end:
            self.fail("pattern ends where an expression was expected")

        char = self.peek()

        if char == "(":
            self.advance()
            if self.pattern.startswith("?:", self.position):
                self.position += 2
                index = None
            else:
                self.groups += 1
                index = self.groups
            inner = self.alternation()
            self.expect(")")
            return Group(inner, index)

        if char == "[":
            return self.char_class()

        if char == "\\":
            return self.escape()

        if char in "^$":
            self.advance()
            return Anchor(char)

        if char == ".":
            self.advance()
            return Any()

        if char in "*+?":
            self.fail("nothing to repeat")

        # A ')' never reaches here: concatenation() stops before it, so a stray
        # one is caught either by expect(')') inside a group or by the leftover
        # check in parse(). A branch for it here would be unreachable.
        self.advance()
        return Literal(char)

    def escape(self) -> Node:
        start = self.position
        self.advance()                                   # backslash
        if self.at_end:
            self.fail("pattern ends with a backslash", start)

        char = self.advance()
        if char.lower() in ESCAPES:
            ranges = ESCAPES[char.lower()]
            return CharClass(list(ranges), negated=char.isupper())
        if char in CONTROL:
            return Literal(CONTROL[char])
        return Literal(char)

    def char_class(self) -> Node:
        start = self.position
        self.advance()                                   # [

        negated = False
        if self.peek() == "^":
            self.advance()
            negated = True

        ranges: list[tuple[str, str]] = []
        first = True
        while True:
            if self.at_end:
                self.fail("unterminated character class", start)
            if self.peek() == "]" and not first:
                self.advance()
                break
            first = False

            low = self.class_char()
            if self.peek() == "-" and self.position + 1 < len(self.pattern) \
                    and self.pattern[self.position + 1] != "]":
                self.advance()
                high = self.class_char()
                if high < low:
                    self.fail(f"[{low}-{high}] counts backwards", start)
                ranges.append((low, high))
            else:
                ranges.append((low, low))

        return CharClass(ranges, negated)

    def class_char(self) -> str:
        char = self.advance()
        if char != "\\":
            return char
        if self.at_end:
            self.fail("character class ends with a backslash")
        escaped = self.advance()
        if escaped in CONTROL:
            return CONTROL[escaped]
        return escaped


def parse(pattern: str) -> tuple[Node, int]:
    return Parser(pattern).parse()
