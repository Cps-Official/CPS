"""
Regression test for a real semantic bug found this session:

The `Program` executor unconditionally auto-called `main()` after
running all top-level statements, *even if the script already called
`main()` explicitly as a top-level statement* -- which is exactly the
idiomatic style used by the repo's own `examples/e1_hello.cpps`
(`++ main <~ () -> int ** { ... }` followed by a bare `main()` call).
Every side effect in `main` (prints, channel sends, mutations) ran
twice. Fixed by scanning the top-level statements for an explicit
`main()` call and skipping the auto-call when one is present, while
still auto-running `main` when the script defines it but never calls
it itself (a separate, intentional convenience feature).
"""
from helpers import run_capture


def test_main_defined_and_called_explicitly_runs_once():
    src = """
    ++ main <~ () -> int ** {
        ~> io::println("hello")
        <- 0
    }
    main()
    """
    assert run_capture(src) == 'hello\n'


def test_main_defined_but_not_called_is_auto_run_once():
    src = """
    ++ main <~ () -> int ** {
        ~> io::println("auto")
        <- 0
    }
    """
    assert run_capture(src) == 'auto\n'


def test_nested_method_named_main_does_not_suppress_auto_run():
    # A method named `main` inside a class is a different binding from
    # the top-level function `main` -- it must not be mistaken for an
    # explicit top-level call when scanning for one.
    src = """
    class Foo -> {
        ++ main <~ () -> void ** { ~> io::println("nested") }
    }
    ++ main <~ () -> int ** {
        ~> io::println("top-level")
        <- 0
    }
    """
    assert run_capture(src) == 'top-level\n'
