"""Integration tests for the compiler-facing pipeline.

These tests intentionally exercise the public layers in order:
lexer/parser -> AST -> semantic -> IR -> optimizer and, for a supported
scalar program, native C11 -> GCC -> executable.
"""

import os
import subprocess
import sys

from helpers import run_capture

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_ROOT, "cpps_native", "src")
sys.path.insert(0, _SRC)

from ir import lower
from lexer import tokenize
from module_loader import ModuleLoader, ModuleError
from native import compile_native
from optimizer import PassManager
from parser import Parser


def _parse(source):
    parser = Parser(tokenize(source, "<integration>"), "<integration>")
    ast = parser.parse()
    assert not parser.errors, parser.errors
    return ast


def test_ir_verifier_and_constant_folding():
    ast = _parse("""
    ++ main <~ () -> int ** {
        x := 1 + 2
        <- x
    }
    """)
    module = lower(ast, "constants")
    reports = PassManager().run(module)
    assert reports[0].changed == 1
    assert "const" in module.format()
    assert "ret" in module.format()


def test_native_backend_builds_and_runs_real_executable(tmp_path):
    ast = _parse("""
    ++ main <~ () -> int ** {
        x :: mut int = 40 + 2
        ~> io::println("answer={}", x)
        <- 0
    }
    main()
    """)
    output = tmp_path / "answer.native"
    result = compile_native(ast, str(output))
    assert output.is_file()
    completed = subprocess.run([str(output)], capture_output=True, text=True)
    assert completed.returncode == 0
    assert completed.stdout == "answer=42\n"
    assert result.compiler_command[0] == "gcc"


def test_native_backend_rejects_unlowered_language_feature(tmp_path):
    ast = _parse("""
    <> i :: [1, 2] ** {
        ~> io::println("{}", i)
    }
    """)
    try:
        compile_native(ast, str(tmp_path / "unsupported.native"))
    except Exception as exc:
        assert "native backend" in str(exc)
    else:
        raise AssertionError("unsupported loop was silently accepted")


def test_module_loader_cache_and_cycle_detection(tmp_path):
    (tmp_path / "a.cpps").write_text("import b\nx := 1\n", encoding="utf-8")
    (tmp_path / "b.cpps").write_text("y := 2\n", encoding="utf-8")
    loader = ModuleLoader([str(tmp_path)])
    module = loader.load("a")
    assert module.imports == ["b"]
    assert loader.load("a") is module
    assert [m.name for m in loader.dependency_order("a")] == ["b", "a"]

    (tmp_path / "b.cpps").write_text("import a\ny := 2\n", encoding="utf-8")
    loader = ModuleLoader([str(tmp_path)])
    try:
        loader.load("a")
    except ModuleError as exc:
        assert "circular" in str(exc)
    else:
        raise AssertionError("cycle was not diagnosed")
