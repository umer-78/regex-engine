"""A static check for patterns that can make a backtracking engine explode.

This is a heuristic and it says so. Deciding whether an arbitrary pattern is
vulnerable is not something a syntactic check can do in general, so this one
looks for the two shapes that cause almost all reported ReDoS — a quantifier
inside a quantifier, and alternatives inside a quantifier that can match the
same character — and reports what it finds with the reason.

It can miss things. It cannot miss the point, which is that the *engine* is the
real fix: none of these shapes cost the automaton engines anything at all.
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
    Repeat,
    parse,
)


@dataclass
class Finding:
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.detail}"


def first_set(node: Node) -> set[str] | None:
    """The characters a node can begin with, or None for "anything".

    Used to decide whether two branches of an alternation can both match the
    same character — if they cannot, the engine never has a real choice to make
    and the nesting is harmless.
    """
    if isinstance(node, Literal):
        return {node.char}
    if isinstance(node, CharClass):
        if node.negated:
            return None
        return {chr(code) for low, high in node.ranges
                for code in range(ord(low), min(ord(high), ord(low) + 256) + 1)}
    if isinstance(node, Any):
        return None
    if isinstance(node, Group):
        return first_set(node.node)
    if isinstance(node, Repeat):
        return first_set(node.node)
    if isinstance(node, Alternate):
        out: set[str] = set()
        for option in node.options:
            inner = first_set(option)
            if inner is None:
                return None
            out |= inner
        return out
    if isinstance(node, Concat):
        for part in node.parts:
            if isinstance(part, Anchor):
                continue
            if isinstance(part, Repeat) and part.minimum == 0:
                inner = first_set(part.node)
                rest = first_set(Concat(node.parts[1:])) if len(node.parts) > 1 else set()
                if inner is None or rest is None:
                    return None
                return inner | rest
            return first_set(part)
        return set()
    if isinstance(node, (Empty, Anchor)):
        return set()
    return None


def overlapping(a: Node, b: Node) -> bool:
    left, right = first_set(a), first_set(b)
    if left is None or right is None:
        return True          # one of them matches anything, so they overlap
    return bool(left & right)


def unbounded(node: Node) -> bool:
    return isinstance(node, Repeat) and node.maximum is None


def analyse(pattern: str) -> list[Finding]:
    node, _groups = parse(pattern)
    findings: list[Finding] = []

    def walk(current: Node, inside_repeat: bool) -> None:
        if isinstance(current, Repeat):
            body = current.node
            if current.maximum is None:
                if contains_unbounded(body):
                    findings.append(Finding(
                        "nested quantifier",
                        "an unbounded repeat inside another unbounded repeat — the "
                        "number of ways to split the input between the two levels "
                        "grows exponentially"))
                if isinstance(strip(body), Alternate):
                    options = strip(body).options
                    for i, left in enumerate(options):
                        for right in options[i + 1:]:
                            if overlapping(left, right):
                                findings.append(Finding(
                                    "ambiguous alternation",
                                    "two branches of an alternation inside a repeat can "
                                    "match the same character, so the engine has a real "
                                    "choice at every position"))
                                break
                        else:
                            continue
                        break
            walk(body, True)
            return

        for child in children(current):
            walk(child, inside_repeat)

    def contains_unbounded(current: Node) -> bool:
        if unbounded(current):
            return True
        return any(contains_unbounded(child) for child in children(current))

    walk(node, False)

    seen = set()
    unique = []
    for finding in findings:
        key = (finding.kind, finding.detail)
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique


def strip(node: Node) -> Node:
    while isinstance(node, Group):
        node = node.node
    return node


def children(node: Node) -> list[Node]:
    if isinstance(node, (Concat,)):
        return list(node.parts)
    if isinstance(node, Alternate):
        return list(node.options)
    if isinstance(node, Group):
        return [node.node]
    if isinstance(node, Repeat):
        return [node.node]
    return []
