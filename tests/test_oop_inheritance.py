"""
Regression tests for class inheritance and `super::method(...)`.

Before this session:
  * `super` was tokenized but never handled by the parser, so
    `super::new(...)` silently parsed as `::new(...)` (empty class
    name) and did nothing.
  * `_instantiate` additionally *pre-constructed* the parent with an
    empty argument list before running the child constructor at all,
    corrupting fields regardless of `super`.
  * A separate, previously-latent bug in `_exec_fn_call` re-ran any
    namespaced call that returned `None` a second time, so once
    `super::method(...)` worked it fired the parent method twice.
These tests pin the fixed behavior down.
"""
from helpers import run_capture


def test_super_new_initializes_inherited_fields():
    src = """
    class Animal -> {
        name :: mut string = ""
        age :: mut int = 0

        ++ new <~ (n: string, a: int) ** {
            @.name = n
            @.age = a
        }
    }

    class Dog : Animal -> {
        breed :: string = "Mixed"

        ++ new <~ (n: string, a: int, b: string) ** {
            super::new(n, a)
            @.breed = b
        }
    }

    d := Dog::new("Rex", 3, "German Shepherd")
    ~> io::println("{} {} {}", d.name, d.age, d.breed)
    """
    assert run_capture(src) == 'Rex 3 German Shepherd\n'


def test_constructor_is_inherited_when_subclass_defines_none():
    src = """
    class Animal -> {
        name :: mut string = "unnamed"
        ++ new <~ (n: string) ** { @.name = n }
    }
    class Dog : Animal -> { }

    d := Dog::new("Rex")
    ~> io::println("{}", d.name)
    """
    assert run_capture(src) == 'Rex\n'


def test_super_method_call_runs_exactly_once():
    """
    Regression test for the `_exec_fn_call` double-dispatch bug: any
    void `super::method(...)` call used to execute its body twice.
    """
    src = """
    class Animal -> {
        ++ speak <~ () -> void ** {
            ~> io::println("sound")
        }
    }
    class Dog : Animal -> {
        ++ speak <~ () -> void ** {
            super::speak()
            ~> io::println("bark")
        }
    }
    d := Dog::new()
    d:speak()
    """
    assert run_capture(src) == 'sound\nbark\n'


def test_multi_level_inheritance_chains_super_calls():
    src = """
    class Animal -> {
        name :: mut string = "unnamed"
        ++ new <~ (n: string) ** { @.name = n }
        ++ speak <~ () -> void ** { ~> io::println("{} makes a sound", @.name) }
    }
    class Dog : Animal -> {
        ++ speak <~ () -> void ** {
            super::speak()
            ~> io::println("{} barks", @.name)
        }
    }
    class Puppy : Dog -> {
        ++ speak <~ () -> void ** {
            super::speak()
            ~> io::println("{} yips", @.name)
        }
    }
    p := Puppy::new("Fido")
    p:speak()
    """
    expected = (
        "Fido makes a sound\n"
        "Fido barks\n"
        "Fido yips\n"
    )
    assert run_capture(src) == expected


def test_overridden_method_and_field_defaults_from_parent():
    src = """
    class Animal -> {
        legs :: mut int = 4
        ++ describe <~ () -> void ** { ~> io::println("legs: {}", @.legs) }
    }
    class Bird : Animal -> {
        ++ new <~ () ** { @.legs = 2 }
    }
    b := Bird::new()
    b:describe()
    """
    assert run_capture(src) == 'legs: 2\n'


def test_static_void_method_runs_exactly_once():
    """
    Regression test: `_exec_fn_call` used to re-run ANY namespaced call
    that returned None a second time, which included plain static
    void methods (not just `super::`).
    """
    src = """
    class Logger -> {
        ++ warn <~ (msg: string) -> void ** {
            ~> io::println("WARN: {}", msg)
        }
    }
    Logger::warn("hello")
    """
    assert run_capture(src) == 'WARN: hello\n'
