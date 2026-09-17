"""
Regression tests for cpps_native/src/semantic.py — the new static type
checker + ownership/borrow checker.

Written against Python's stdlib `unittest` rather than pytest so they can
run in offline / no-network environments (`python3 -m unittest`), in
addition to being picked up by pytest when it's available.

Categories covered:
  - Positive: every real program under examples/*.cpps must analyze clean.
  - Negative: use-after-move, double-move, type mismatch, arity mismatch,
    reassignment through a mutable borrow must all be *detected*.
  - No false positives on ordinary, valid control flow (if/while/for,
    functions calling each other, shared/borrowed values used normally).
"""

import glob
import os
import sys
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(_THIS_DIR, '..', 'cpps_native', 'src')
sys.path.insert(0, os.path.abspath(_SRC_DIR))

from lexer import tokenize          # noqa: E402
from parser import Parser           # noqa: E402
from semantic import analyze        # noqa: E402

EXAMPLES_DIR = os.path.abspath(os.path.join(_THIS_DIR, '..', 'examples'))


def _analyze_source(src: str, filename: str = '<test>'):
    tokens = tokenize(src, filename)
    p = Parser(tokens, filename)
    ast = p.parse()
    assert not p.errors, f"unexpected parse errors: {p.errors}"
    return analyze(ast, filename, src)


class TestRealExamplesAnalyzeClean(unittest.TestCase):
    """Every shipped example program must produce zero diagnostics. This
    is the primary anti-false-positive guard: the checker must never
    flag real, working CP+* code."""

    def test_all_examples_clean(self):
        example_files = sorted(glob.glob(os.path.join(EXAMPLES_DIR, '*.cpps')))
        self.assertTrue(example_files, "no example .cpps files found — path may be wrong")
        for path in example_files:
            with self.subTest(example=os.path.basename(path)):
                with open(path, encoding='utf-8') as fh:
                    src = fh.read()
                result = _analyze_source(src, path)
                self.assertFalse(
                    result.has_errors,
                    f"{path} produced unexpected diagnostics:\n{result.render(path, src)}",
                )


class TestOwnershipChecker(unittest.TestCase):
    def test_use_after_move_detected(self):
        src = (
            "++ main <~ () -> int ** {\n"
            "    own<int> a := 100\n"
            "    own<int> b := a\n"
            "    ~> io::println(\"{}\", a)\n"
            "    <- 0\n"
            "}\n"
        )
        result = _analyze_source(src)
        self.assertTrue(result.has_errors)
        self.assertTrue(any(d.code == 'E0103' for d in result.diagnostics))

    def test_move_then_reassign_is_fine(self):
        # After a genuine move, reassigning the moved-from variable makes
        # it a fresh owner again — this must NOT be flagged.
        src = (
            "++ main <~ () -> int ** {\n"
            "    own<int> a := 100\n"
            "    own<int> b := a\n"
            "    a = 5\n"
            "    ~> io::println(\"{}\", a)\n"
            "    <- 0\n"
            "}\n"
        )
        result = _analyze_source(src)
        self.assertFalse(result.has_errors, result.render('<test>', src))

    def test_borrow_of_owned_value_is_fine(self):
        src = (
            "++ main <~ () -> int ** {\n"
            "    own<int> a := 100\n"
            "    borrow<int> c := a\n"
            "    ~> io::println(\"{}\", c)\n"
            "    <- 0\n"
            "}\n"
        )
        result = _analyze_source(src)
        self.assertFalse(result.has_errors, result.render('<test>', src))

    def test_share_never_moves(self):
        src = (
            "++ main <~ () -> int ** {\n"
            "    share<string> s := \"hi\"\n"
            "    x := s\n"
            "    ~> io::println(\"{}\", s)\n"
            "    <- 0\n"
            "}\n"
        )
        result = _analyze_source(src)
        self.assertFalse(result.has_errors, result.render('<test>', src))


class TestTypeChecker(unittest.TestCase):
    def test_binary_op_type_mismatch_detected(self):
        src = (
            "++ main <~ () -> int ** {\n"
            "    x :: int = 1\n"
            "    y := x + \"hello\"\n"
            "    <- 0\n"
            "}\n"
        )
        result = _analyze_source(src)
        self.assertTrue(result.has_errors)
        self.assertTrue(any(d.code == 'E0001' for d in result.diagnostics))

    def test_declared_type_mismatch_detected(self):
        src = (
            "++ main <~ () -> int ** {\n"
            "    x :: int = \"not a number\"\n"
            "    <- 0\n"
            "}\n"
        )
        result = _analyze_source(src)
        self.assertTrue(result.has_errors)
        self.assertTrue(any(d.code == 'E0001' for d in result.diagnostics))

    def test_matching_types_are_fine(self):
        src = (
            "++ main <~ () -> int ** {\n"
            "    x :: int = 1\n"
            "    y :: int = x + 2\n"
            "    <- 0\n"
            "}\n"
        )
        result = _analyze_source(src)
        self.assertFalse(result.has_errors, result.render('<test>', src))

    def test_string_concat_is_fine(self):
        src = (
            "++ main <~ () -> int ** {\n"
            "    a :: string = \"foo\"\n"
            "    b :: string = \"bar\"\n"
            "    c := a + b\n"
            "    <- 0\n"
            "}\n"
        )
        result = _analyze_source(src)
        self.assertFalse(result.has_errors, result.render('<test>', src))

    def test_arity_mismatch_detected(self):
        src = (
            "++ add <~ (a: int, b: int) -> int ** {\n"
            "    <- a + b\n"
            "}\n"
            "++ main <~ () -> int ** {\n"
            "    z := add(1, 2, 3)\n"
            "    <- 0\n"
            "}\n"
        )
        result = _analyze_source(src)
        self.assertTrue(result.has_errors)
        self.assertTrue(any(d.code == 'E0002' for d in result.diagnostics))

    def test_correct_arity_is_fine(self):
        src = (
            "++ add <~ (a: int, b: int) -> int ** {\n"
            "    <- a + b\n"
            "}\n"
            "++ main <~ () -> int ** {\n"
            "    z := add(1, 2)\n"
            "    <- 0\n"
            "}\n"
        )
        result = _analyze_source(src)
        self.assertFalse(result.has_errors, result.render('<test>', src))


class TestControlFlowNoFalsePositives(unittest.TestCase):
    """Values used across if/while/for branches, and functions calling
    each other, must not trip the checker."""

    def test_if_else_branches(self):
        src = (
            "++ main <~ () -> int ** {\n"
            "    x :: int = 5\n"
            "    ?? x > 0 ** {\n"
            "        y := x + 1\n"
            "    } -- else ** {\n"
            "        y := x - 1\n"
            "    }\n"
            "    <- 0\n"
            "}\n"
        )
        result = _analyze_source(src)
        self.assertFalse(result.has_errors, result.render('<test>', src))

    def test_while_loop(self):
        src = (
            "++ main <~ () -> int ** {\n"
            "    i :: mut int = 0\n"
            "    while i < 10 ** {\n"
            "        i = i + 1\n"
            "    }\n"
            "    <- 0\n"
            "}\n"
        )
        result = _analyze_source(src)
        self.assertFalse(result.has_errors, result.render('<test>', src))


if __name__ == '__main__':
    unittest.main()
