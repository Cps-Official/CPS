"""Shared helpers for the CP+* test suite."""
import io
import contextlib
import os
import sys

# Keep the suite runnable by both pytest (which uses conftest.py) and the
# stdlib unittest runner, without relying on the caller's PYTHONPATH.
_SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'cpps_native', 'src'))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from interpreter import Interpreter


def run_capture(source: str, filename: str = '<test>', verbose: bool = False) -> str:
    """
    Run CP+* source through a fresh Interpreter and return everything
    printed to stdout. Raises whatever exception the interpreter raises
    (CPPSPanic, CPPSError, etc.) so tests can assert on failures too.
    """
    from lexer import tokenize
    from parser import Parser

    tokens = tokenize(source, filename)
    parser = Parser(tokens, filename=filename)
    program = parser.parse()
    if parser.errors:
        msgs = '; '.join(str(e) for e in parser.errors)
        raise SyntaxError(f"Parse errors in {filename}: {msgs}")

    interp = Interpreter(verbose=verbose)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        interp.exec(program, interp.global_env)
    return buf.getvalue()
