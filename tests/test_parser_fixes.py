"""
Regression tests for parser-level fixes made this session:
  * `Type::method(args)` used as a bare statement was misparsed as a
    variable declaration (`Type :: method = args`).
  * OR-patterns (`1 | 2 | 3 => ...`) were documented but never parsed
    (the interpreter already supported the `OrPattern` AST node; only
    the parser was missing).
  * `value is none` (documented in the README) was not a recognized
    comparison at all.
  * `|x| expr` lambda literals were documented (used throughout the
    stdlib docs for :map/:filter/:reduce) but not parseable — the
    interpreter's `LambdaExpr`/`CPPSClosure` machinery existed but was
    unreachable from any surface syntax.
"""
from helpers import run_capture


def test_static_call_as_bare_statement():
    src = """
    class Logger -> {
        ++ warn <~ (msg: string) -> void ** {
            ~> io::println("WARN: {}", msg)
        }
    }
    Logger::warn("disk low")
    """
    assert run_capture(src) == 'WARN: disk low\n'


def test_or_pattern_matches_any_alternative():
    src = """
    <> v :: [0, 1, 2, 3, 50, 200] ** {
        ?~ v {
            0 => { ~> io::println("zero") },
            1 | 2 | 3 => { ~> io::println("small: {}", v) },
            x if x > 100 => { ~> io::println("large: {}", x) },
            _ => { ~> io::println("other: {}", v) }
        }
    }
    """
    expected = (
        "zero\n"
        "small: 1\n"
        "small: 2\n"
        "small: 3\n"
        "other: 50\n"
        "large: 200\n"
    )
    assert run_capture(src) == expected


def test_is_none_comparison():
    src = """
    x := none
    y := 5
    ?? x is none ** { ~> io::println("x is none") }
    ?? y is none ** { ~> io::println("y is none") } -- else ** { ~> io::println("y is not none") }
    """
    assert run_capture(src) == 'x is none\ny is not none\n'


def test_lambda_literal_basic():
    src = """
    add5 := |x| x + 5
    ~> io::println("{}", add5(10))
    """
    assert run_capture(src) == '15\n'


def test_lambda_closes_over_enclosing_variable():
    src = """
    ++ make_adder <~ (n: int) -> auto ** {
        <- |x| x + n
    }
    add5 := make_adder(5)
    add10 := make_adder(10)
    ~> io::println("{} {}", add5(1), add10(1))
    """
    assert run_capture(src) == '6 11\n'


def test_lambda_with_collection_methods():
    src = """
    ~> io::println("{}", [1, 2, 3]:map(|x| x * 2))
    ~> io::println("{}", [1, 2, 3]:filter(|x| x > 1))
    ~> io::println("{}", [1, 2, 3]:reduce(|a, b| a + b))
    """
    assert run_capture(src) == '[2, 4, 6]\n[2, 3]\n6\n'
