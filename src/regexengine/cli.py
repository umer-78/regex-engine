"""rex: run a regular expression through four engines and compare them."""

from __future__ import annotations

import argparse
import os
import re as stdlib_re
import sys
import time

from . import __version__
from .backtrack import Backtracking, StepLimit
from .dfa import LazyDFA
from .program import compile_pattern, disassemble
from .safety import analyse
from .thompson import Pike, Thompson


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rex", description=__doc__)
    parser.add_argument("--version", action="version", version=f"rex {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    match = sub.add_parser("match", help="run every engine and compare")
    match.add_argument("pattern")
    match.add_argument("text")
    match.add_argument("--limit", type=int, default=1_000_000,
                       help="step budget for the backtracking engine")
    match.add_argument("--stdlib-guard", type=int, default=24,
                       help="skip python's re above this input length when the pattern "
                            "is flagged; it is a backtracking engine too. 0 disables the guard")

    groups = sub.add_parser("groups", help="show the capture groups")
    groups.add_argument("pattern")
    groups.add_argument("text")

    compile_cmd = sub.add_parser("compile", help="disassemble the compiled program")
    compile_cmd.add_argument("pattern")

    check = sub.add_parser("check", help="look for shapes that can make backtracking explode")
    check.add_argument("pattern", nargs="+")

    redos = sub.add_parser("redos", help="measure how the backtracking cost grows")
    redos.add_argument("pattern", nargs="?", default="(a+)+b")
    redos.add_argument("-u", "--unit", default="a", help="the repeated part of the input")
    redos.add_argument("-s", "--suffix", default="!", help="the character that makes it fail")
    redos.add_argument("-m", "--max", type=int, default=22)
    redos.add_argument("--stdlib", action="store_true",
                       help="time Python's own re module on the same input")

    bench = sub.add_parser("bench", help="where the lazy DFA wins and where it loses")
    bench.add_argument("-n", "--length", type=int, default=20000)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Wraps the real work so piping into `head` — which closes the
    pipe early — ends quietly instead of printing a BrokenPipeError."""
    try:
        return _run(argv)
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130
    except ValueError as error:
        print(f"rex: {error}", file=sys.stderr)
        return 2


def _run(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "compile":
        program, groups = compile_pattern(args.pattern)
        print(f"{args.pattern}   ({len(program)} instructions, {groups} capture group(s))\n")
        print(disassemble(program))
        return 0

    if args.cmd == "check":
        worst = 0
        for pattern in args.pattern:
            findings = analyse(pattern)
            if not findings:
                print(f"ok    {pattern}")
                continue
            worst = 1
            print(f"RISK  {pattern}")
            for finding in findings:
                print(f"        {finding.kind}")
                print(f"        {finding.detail}")
        print("\nThis is a heuristic over the pattern's shape. It says a pattern *can*")
        print("explode on some input; finding that input is a separate problem. None")
        print("of these shapes cost the automaton engines anything.")
        return worst

    if args.cmd == "redos":
        return redos(args)

    if args.cmd == "bench":
        return bench(args.length)

    if args.cmd == "groups":
        engine = Pike(args.pattern)
        found = engine.search(args.text)
        if not found:
            print("no match")
            return 1
        print(f"match {found.matched!r} at {found.start}..{found.end}")
        for index in range(1, engine.group_count + 1):
            print(f"  group {index}: {found.group(index)!r}")
        return 0

    # match
    print(f"pattern {args.pattern!r}   text {args.text!r}\n")
    print(f"{'engine':<16}{'result':>9}{'steps':>14}{'time':>10}")

    results = {}

    backtracking = Backtracking(args.pattern, limit=args.limit)
    start = time.perf_counter()
    try:
        results["backtracking"] = backtracking.matches(args.text)
        elapsed = time.perf_counter() - start
        print(f"{'backtracking':<16}{results['backtracking']!s:>9}{backtracking.steps:>14,}{elapsed:>10.4f}")
    except StepLimit as error:
        elapsed = time.perf_counter() - start
        print(f"{'backtracking':<16}{'GAVE UP':>9}{error.steps:>14,}{elapsed:>10.4f}")

    nfa = Thompson(args.pattern)
    start = time.perf_counter()
    results["thompson"] = nfa.matches(args.text)
    elapsed = time.perf_counter() - start
    print(f"{'thompson nfa':<16}{results['thompson']!s:>9}{nfa.trace.steps:>14,}{elapsed:>10.4f}")

    lazy = LazyDFA(args.pattern)
    start = time.perf_counter()
    results["dfa"] = lazy.matches(args.text)
    elapsed = time.perf_counter() - start
    print(f"{'lazy dfa':<16}{results['dfa']!s:>9}{lazy.trace.steps:>14,}{elapsed:>10.4f}")

    risky = bool(analyse(args.pattern))
    if risky and args.stdlib_guard > 0 and len(args.text) > args.stdlib_guard:
        # Python's re is a backtracking engine, so on a flagged pattern it has
        # the same exponential blow-up this project is about. Running it anyway
        # would hang the tool — which proves the point, and is not a useful way
        # to spend the user's afternoon.
        print(f"{'python re':<16}{'skipped':>9}{'-':>14}{'-':>10}")
        print(f"\npython re was skipped: {args.pattern!r} is flagged, python's re is a")
        print(f"backtracking engine, and the input is over {args.stdlib_guard} characters. Pass")
        print("--stdlib-guard 0 to run it anyway, or `rex redos --stdlib` to watch it grow.")
    else:
        start = time.perf_counter()
        results["python re"] = bool(stdlib_re.search(args.pattern, args.text))
        elapsed = time.perf_counter() - start
        print(f"{'python re':<16}{results['python re']!s:>9}{'-':>14}{elapsed:>10.4f}")

    print(f"\nall engines agree: {len(set(results.values())) == 1}")
    return 0


def redos(args) -> int:
    print(f"pattern {args.pattern!r}, input {args.unit!r} x n + {args.suffix!r}\n")
    header = f"{'n':>4}{'backtracking':>16}{'thompson':>12}{'ratio':>12}"
    if args.stdlib:
        header += f"{'python re':>12}"
    print(header)

    previous = None
    for n in range(2, args.max + 1):
        text = args.unit * n + args.suffix

        engine = Backtracking(args.pattern, limit=200_000_000)
        try:
            engine.matches(text)
            steps = engine.steps
            gave_up = False
        except StepLimit as error:
            steps = error.steps
            gave_up = True

        nfa = Thompson(args.pattern)
        nfa.matches(text)

        row = (f"{n:>4}{('>' if gave_up else '') + format(steps, ','):>16}"
               f"{nfa.trace.steps:>12,}{steps / nfa.trace.steps:>11,.0f}x")
        if args.stdlib:
            start = time.perf_counter()
            stdlib_re.search(args.pattern, text)
            row += f"{time.perf_counter() - start:>11.3f}s"
        print(row)

        growth = steps / previous if previous else None
        previous = steps
        if gave_up:
            print("\nthe backtracking engine hit its step budget — without one it would "
                  "keep going.")
            break

    print()
    if growth and growth > 1.9:
        print(f"every extra character multiplies the backtracking work by {growth:.2f}, "
              "which is exponential.")
    elif growth:
        print(f"every extra character multiplies the backtracking work by {growth:.2f}, "
              "which is not an explosion.")
    print("the automaton engine's cost is linear in the input and independent of the "
          "pattern's shape.")
    return 0


def bench(length: int) -> int:
    import random

    rng = random.Random(1)
    print(f"{length:,} characters\n")
    print(f"{'pattern':<14}{'dfa':>10}{'nfa':>10}{'states':>9}{'cache hits':>12}{'verdict':>16}")

    ordinary = "".join(rng.choice("abcdefg") for _ in range(length))
    tail = "".join(rng.choice("ab") for _ in range(min(length, 2000)))

    cases = [(r"[0-9]+", ordinary), (r"x[yz]w", ordinary), (r"a(b|c)*q", ordinary),
             (r"a.{6}$", tail + "b" * 7), (r"a.{10}$", tail + "b" * 11),
             (r"a.{14}$", tail + "b" * 15)]

    for pattern, text in cases:
        lazy = LazyDFA(pattern)
        start = time.perf_counter()
        lazy.matches(text)
        dfa_time = time.perf_counter() - start

        nfa = Thompson(pattern)
        start = time.perf_counter()
        nfa.matches(text)
        nfa_time = time.perf_counter() - start

        if dfa_time < nfa_time:
            verdict = f"dfa {nfa_time / dfa_time:.1f}x faster"
        else:
            verdict = f"dfa {dfa_time / nfa_time:.1f}x slower"
        print(f"{pattern:<14}{dfa_time:>9.4f}s{nfa_time:>9.4f}s{lazy.trace.states_built:>9,}"
              f"{100 * lazy.trace.hit_rate:>11.1f}%{verdict:>16}")

    print("\nthe lazy dfa wins when its states get reused and loses when they do not.")
    return 0
