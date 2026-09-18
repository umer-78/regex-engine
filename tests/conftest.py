import pytest

from regexengine import Backtracking, LazyDFA, Pike, Thompson


def all_engines(pattern: str, text: str) -> dict[str, bool]:
    """Every engine's yes-or-no answer, for the agreement tests."""
    return {
        "backtracking": Backtracking(pattern).matches(text),
        "thompson": Thompson(pattern).matches(text),
        "dfa": LazyDFA(pattern).matches(text),
        "pike": Pike(pattern).search(text) is not None,
    }


@pytest.fixture()
def engines():
    return all_engines
