"""
Regression tests for control-flow fixes made in this session:

  * `loop { ... }` was not a recognized keyword anywhere in
    tokens.py/parser.py -- it parsed as an undefined-variable
    reference followed by a block that ran exactly once. It is now
    KW_LOOP, desugaring at parse time to `WhileStmt(Literal(True), body)`,
    so it gets break/continue/interpreter support for free from the
    existing `while` implementation. (The equivalent xfail test in
    test_known_gaps.py -- test_bare_loop_statement -- was converted to
    a real assertion in the same change.)

  * Range expressions (`start..end`, `start..=end`) were fully
    supported at the *interpreter* level (`RangeExpr` evaluated to a
    materialized list of ints) but the *parser* never constructed a
    RangeExpr node in general expression position -- only inside match
    patterns. `0..5` as a for-loop iterable, or as a plain expression,
    was a parse error / treated `.` as a decimal point / silently
    misparsed. Added a `parse_range()` precedence level (between
    comparison and additive) so ranges now work anywhere an expression
    is valid, most commonly `<> i :: start..end ** { ... }`.
"""
from helpers import run_capture


def test_loop_with_break():
    src = """
    count :: mut int = 0
    loop {
        count += 1
        ?? count >= 3 ** { !> }
    }
    ~> io::println("{}", count)
    """
    assert run_capture(src) == '3\n'


def test_loop_with_continue_and_break():
    # Skip printing even numbers, stop after printing three odd ones.
    src = """
    n :: mut int = 0
    printed :: mut int = 0
    loop {
        n += 1
        ?? n % 2 == 0 ** { !>> }
        ~> io::println("{}", n)
        printed += 1
        ?? printed >= 3 ** { !> }
    }
    """
    assert run_capture(src) == '1\n3\n5\n'


def test_range_exclusive_in_for_loop():
    src = """
    <> i :: 0..5 ** {
        ~> io::println("{}", i)
    }
    """
    assert run_capture(src) == '0\n1\n2\n3\n4\n'


def test_range_inclusive_in_for_loop():
    src = """
    <> i :: 1..=3 ** {
        ~> io::println("{}", i)
    }
    """
    assert run_capture(src) == '1\n2\n3\n'


def test_range_with_expression_bounds():
    # Ranges bind looser than `+`/`-`, so `a+1..b-1` is `(a+1)..(b-1)`.
    src = """
    a := 0
    b := 6
    <> i :: a+1..b-1 ** {
        ~> io::println("{}", i)
    }
    """
    assert run_capture(src) == '1\n2\n3\n4\n'


def test_range_with_variable_bounds_and_break():
    src = """
    lo := 10
    hi := 20
    found :: mut int = -1
    <> i :: lo..hi ** {
        ?? i == 15 ** {
            found = i
            !>
        }
    }
    ~> io::println("{}", found)
    """
    assert run_capture(src) == '15\n'