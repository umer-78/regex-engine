# rex

[![CI](https://github.com/umer-78/regex-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/umer-78/regex-engine/actions/workflows/ci.yml)

**Live demo:** https://umer-78.github.io/regex-engine/

A regular expression engine written from scratch in Python with no
dependencies: a parser, a backtracking matcher, Thompson's NFA simulation, and a
lazy DFA — four engines over one pattern, so the thing every ReDoS advisory is
about can be measured instead of described.

```
$ rex match '(a+)+b' 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
engine             result         steps      time
backtracking      GAVE UP     1,000,001    0.8020
thompson nfa        False           875    0.0002
lazy dfa            False           100    0.0002
python re         skipped             -         -

python re was skipped: '(a+)+b' is flagged, python's re is a
backtracking engine, and the input is over 24 characters.
```

- **217 tests**, Python 3.10–3.12, standard library only
- Every engine is checked against Python's own `re` on 60 hand-picked cases and
  600 randomly generated patterns
- A static check for the pattern shapes that cause almost all reported ReDoS

## Quick start

```bash
git clone https://github.com/umer-78/regex-engine.git
cd regex-engine
pip install -e ".[dev]"
pytest -q                              # 217 tests

rex match   'a+b' 'xaaab'
rex groups  '(\w+)@(\w+)' 'mail user@example now'
rex compile 'a(b|c)*d'
rex check   '(a+)+b' '^\w+@\w+\.\w+$'
rex redos   --stdlib
rex bench
```

## Every character doubles the work

`(a+)+b` against a string of `a` with no `b`. There is no match, so a
backtracking engine has to try every way of dividing the input between the outer
and inner `+` before it can say so:

```
$ rex redos -m 20 --stdlib
   n    backtracking    thompson       ratio   python re
  12          65,522         352        186x      0.000s
  14         262,128         412        636x      0.002s
  16       1,048,558         472      2,222x      0.007s
  18       4,194,284         532      7,884x      0.026s
  20      16,777,194         592     28,340x      0.106s

every extra character multiplies the backtracking work by 2.00, which is exponential.
```

Both columns have exact closed forms, and the tests assert them rather than
eyeballing a curve:

| engine | steps for n characters |
| --- | --- |
| backtracking | **2^(n+4) − (n+9)** |
| Thompson NFA | **30n − 25** |

At twenty characters that is 16.7 million steps against 592 — and twenty
characters is a short input. Thirty takes this backtracking engine longer than
you will wait, which is why `rex match` gives it a step budget by default.

**Python's own `re` is in the same column.** It is a backtracking engine, so the
last column doubles too: 0.106 s at n=20, 1.6 s at n=24, 25 s at n=28. That is
not a criticism of Python — Perl, Java, JavaScript, .NET and Ruby all ship
backtracking engines, because backreferences and lookaround need them — but it
is why a regular expression built from user input is a denial of service waiting
for a slow afternoon.

`rex match` refuses to run the stdlib on a flagged pattern over 24 characters,
because proving the point by hanging the tool for four minutes is not a useful
way to prove it.

## The reason: paths versus positions

The backtracking engine explores *paths* through the automaton, and there are
exponentially many. The Thompson simulation advances *positions* — the set of
program addresses that are live — and there are at most as many as the program
has instructions. Two paths that arrive at the same address are the same
position from then on, and one line is what collapses them:

```python
def add(self, threads, address, text, position):
    if address in threads:
        return          # <- this line is the whole difference
    threads.add(address)
```

Without it, the simulation is the backtracking engine written differently. With
it, the work is bounded by `len(text) × len(program)` no matter what the pattern
looks like. Same automaton; different quantity being enumerated.

The price is capture groups. Tracking which thread captured what needs a slot
array copied per thread, which is why `Pike` is slower than the plain membership
test — and backreferences are not supported at all, because they make the
language non-regular. Every engine that offers them is a backtracking engine,
and that is the trade the whole industry made.

## Catastrophic backtracking needs a failure

The same pattern against an input that *does* match returns on the first
successful path:

| input | backtracking steps |
| --- | --- |
| 18 `a` and no `b` (fails) | **4,194,277** |
| 18 `a` followed by `b` (matches) | **49** |

Eighty-five thousand times apart, same pattern, one character different. This is
why a vulnerable pattern sails through testing: the test suite feeds it inputs
that match.

## A static check for the shapes that explode

```
$ rex check '(a+)+b' '(a|a)*b' '(a|b)*c' '^\w+@\w+\.\w+$'
RISK  (a+)+b
        nested quantifier
        an unbounded repeat inside another unbounded repeat — the number of
        ways to split the input between the two levels grows exponentially
RISK  (a|a)*b
        ambiguous alternation
        two branches of an alternation inside a repeat can match the same
        character, so the engine has a real choice at every position
ok    (a|b)*c
ok    ^\w+@\w+\.\w+$
```

`(a|a)*b` and `(a|b)*c` look identical and are not: in the first, both branches
match `a`, so at every character the engine has a real choice to un-make later.
In the second they are disjoint, there is never a choice, and the cost stays
linear. The checker computes each branch's first-set and reports the overlap.

Two honest limits, both stated by the tool itself:

- It is a **heuristic over the pattern's shape**. Deciding this in general is not
  something a syntactic check can do, and a checker that implies completeness is
  worse than no checker.
- It tells you a pattern *can* explode, not that any particular input will.
  `^(\s*\w+)+$` is flagged and is the classic vulnerable pattern — but it is
  linear against `"a b a b …!"` and exponential against `"aaaa…!"`. Finding the
  input is a separate problem.

The measurements back the flags. Over the patterns in the test suite, every
flagged one grows at ≥1.9× per character on its worst input and every unflagged
one stays under 1.2×.

## The lazy DFA wins until its states stop being reused

Caching each distinct set of live addresses turns matching into one table lookup
per character. The textbook warning is that the number of distinct sets can be
exponential in the pattern; the part worth measuring is what that costs in
practice:

```
$ rex bench -n 20000
pattern              dfa       nfa   states  cache hits         verdict
[0-9]+           0.0072s   0.0224s        3      100.0% dfa 3.1x faster
x[yz]w           0.0062s   0.0146s        3      100.0% dfa 2.4x faster
a(b|c)*q         0.0064s   0.0263s        6      100.0% dfa 4.1x faster
a.{6}$           0.0018s   0.0053s      130       93.5% dfa 3.0x faster
a.{10}$          0.0111s   0.0076s    1,307       35.0% dfa 1.5x slower
a.{14}$          0.0166s   0.0093s    1,956        3.0% dfa 1.8x slower
```

The cache hit rate is the whole story. `a.{k}$` needs to remember which of the
last k characters was an `a`, which is 2^k states; building them lazily caps that
at the number the input actually visits, but once the hit rate collapses the DFA
is paying construction costs per character and loses to the NFA it was built
from. A DFA is a bet that states get reused, and the bet is visible in one
column.

Building the table lazily is also what keeps it from being a memory
denial-of-service: the cache has a limit, and reaching it clears the table rather
than growing without bound. An engine that trades an exponential-time attack for
an exponential-memory one has not fixed anything.

## What a `$` costs a DFA, and a bug it caused

`^` and `$` make the transition function depend on *where* in the input you are,
not just on the character. The first version of the DFA cached transitions by
character alone, so a transition worked out in the middle of a string was reused
at its end — and **every pattern ending in `$` silently failed to match**.

The hand-written test cases did not catch it. The test that generates 600 random
patterns and compares every engine against Python's `re` caught it on the first
run, with five examples. The fix is to include the assertion context in the cache
key; the lesson is that hand-picked cases test what the author already thought
of, which is the same set of things the implementation already handles.

## What it supports

Literals, `.`, character classes with ranges and negation, `\d \w \s` and their
uppercase complements, `*` `+` `?` and `{n,m}` in greedy and lazy forms,
alternation, capturing and non-capturing groups, and the `^` `$` anchors.
Leftmost-first semantics, so `a|ab` against `"ab"` gives `"a"` — the first
alternative that works, not the longest — which is what Python does and what
almost every engine that is not POSIX does.

Not supported: backreferences and lookaround. They are why backtracking engines
exist, and adding them would mean giving up the guarantee this project is about.

```
$ rex compile 'a(b|c)*d'
   0  char 'a'
   1  split 2, 9
   2  save 2
   3  split 4, 6
   4  char 'b'
   5  jump 7
   6  char 'c'
   7  save 3
   8  jump 1
   9  char 'd'
  10  match
```

## Layout

```
src/regexengine/
  syntax.py      pattern text to a tree, with the position of every error
  program.py     Thompson's construction: the tree to an instruction program
  backtrack.py   the engine almost everyone writes, with a step budget
  thompson.py    the parallel simulation, and Pike's version with captures
  dfa.py         the lazy DFA, and what its cache costs
  safety.py      the static check, with its limits stated
  cli.py         match, groups, compile, check, redos, bench
tests/           217 tests
```

## Tests

```
$ pytest -q
217 passed
```

The suite is built around one idea: **Python's `re` is the reference**. Sixty
hand-picked cases covering every construct and boundary are checked against it,
and then six hundred randomly generated patterns are checked against it as well —
which is the test that found the `$` bug. On top of that sit the measurements:
the two closed forms for step counts, the flagged-versus-safe growth rates, and
the capture groups compared against `re`'s group by group.

## Licence

MIT.
