"""
Pytest configuration for the CP+* test suite.

CP+*'s own modules (lexer.py, parser.py, interpreter.py, tokens.py) use
flat, non-package imports (e.g. `from tokens import ...`) and rely on
cpps.py inserting `cpps_native/src` onto sys.path at runtime. We mirror
that exact mechanism here so tests exercise the real import path the
CLI uses, instead of a different (and potentially divergent) packaged
import.
"""
import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TESTS_DIR)
_SRC_DIR = os.path.join(_REPO_ROOT, 'cpps_native', 'src')

if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
