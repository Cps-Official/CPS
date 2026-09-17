"""
These are former documented gaps retained as ordinary regression tests.
They stay in this file because each test represents a bug found during the
audit and prevents the behavior from regressing.
"""
from helpers import run_capture


def test_bare_loop_statement():
    """
    `loop { ... }` is now implemented (KW_LOOP, desugars to
    `while true { ... }` at parse time) -- this used to be an xfail
    known-gap test; it's a real assertion now that the feature works.
    """
    src = """
    count :: mut int = 0
    loop {
        count += 1
        ?? count >= 3 ** { !> }
    }
    ~> io::println("{}", count)
    """
    assert run_capture(src) == '3\n'


def test_word_break_keyword():
    src = """
    count :: mut int = 0
    while true ** {
        count += 1
        ?? count >= 3 ** { break }
    }
    ~> io::println("{}", count)
    """
    assert run_capture(src) == '3\n'


def test_int_return_type_is_enforced():
    src = """
    ++ divide <~ (a: int, b: int) -> int ** {
        <- a / b
    }
    ~> io::println("{}", divide(10, 2))
    """
    assert run_capture(src) == '5\n'
