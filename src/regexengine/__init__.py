"""A regular expression engine from scratch: parser, backtracking matcher,
Thompson NFA simulation and a lazy DFA."""

from .backtrack import Backtracking, StepLimit
from .dfa import LazyDFA
from .program import compile_pattern, disassemble
from .safety import Finding, analyse
from .syntax import RegexError, parse
from .thompson import Pike, Thompson

__all__ = [
    "Backtracking", "Finding", "LazyDFA", "Pike", "RegexError", "StepLimit",
    "Thompson", "analyse", "compile_pattern", "disassemble", "parse",
]
__version__ = "1.0.0"


def matches(pattern: str, text: str) -> bool:
    """Match with the automaton engine, which cannot blow up."""
    return Thompson(pattern).matches(text)


def search(pattern: str, text: str):
    """Match with captures, still without backtracking."""
    return Pike(pattern).search(text)
