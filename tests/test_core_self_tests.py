"""
Wraps CP+*'s own built-in self-test functions (`lexer._run_tests`,
`interpreter._run_tests`) so `pytest` fails loudly if either regresses,
instead of the failure only being visible as printed text a human has
to notice.
"""
import io
import contextlib

import pytest


def test_lexer_self_tests_pass():
    from lexer import _run_tests

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _run_tests()
    output = buf.getvalue()
    assert '0 failed' in output, output
    assert '❌' not in output, output


def test_interpreter_self_tests_pass():
    from interpreter import _run_tests

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _run_tests()
    output = buf.getvalue()
    assert '0 failed' in output, output
    assert '❌' not in output, output


@pytest.mark.parametrize('source,expected', [
    ('~> io::println("{}", 1 + 1)', '2\n'),
    ('~> io::println("{}", "a" + "b")', 'ab\n'),
    ('~> io::println("{}", true && false)', 'false\n'),
    ('~> io::println("{}", true || false)', 'true\n'),
    ('~> io::println("{}", 5 > 3)', 'true\n'),
])
def test_basic_expressions(source, expected):
    from helpers import run_capture
    assert run_capture(source) == expected


def test_variable_binding_and_mutation():
    from helpers import run_capture
    src = """
    x :: mut int = 0
    x = x + 1
    x += 4
    ~> io::println("{}", x)
    """
    assert run_capture(src) == '5\n'


def test_function_and_recursion():
    from helpers import run_capture
    src = """
    ++ factorial <~ (n: int) -> int ** {
        ?? n <= 1 ** {
            <- 1
        } -- else ** {
            <- n * factorial(n - 1)
        }
    }
    ~> io::println("{}", factorial(5))
    """
    assert run_capture(src) == '120\n'


def test_closures_capture_environment():
    from helpers import run_capture
    src = """
    ++ make_adder <~ (n: int) -> auto ** {
        <- |x| x + n
    }
    add5 := make_adder(5)
    ~> io::println("{}", add5(10))
    """
    assert run_capture(src) == '15\n'
