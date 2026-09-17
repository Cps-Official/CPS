"""Native C11 backend for the scalar CP+* subset.

This is a genuine native backend: CP+* AST is translated to C, GCC produces
an ELF executable, and the executable can be run without importing the CP+*
interpreter.  Unsupported language features fail loudly with a source-aware
diagnostic instead of silently falling back to Python.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from parser import (
    ASTNode, BinaryOp, FnCall, FnDef, IfStmt, Literal, PipeStmt,
    Program, ReturnStmt, VarDecl, VarRef,
)


class NativeCompileError(Exception):
    pass


@dataclass
class NativeResult:
    executable: str
    c_source: str
    compiler_command: List[str] = field(default_factory=list)


class CBackend:
    def __init__(self):
        self.lines: List[str] = []
        self.types: Dict[str, str] = {}
        self.functions: Dict[str, FnDef] = {}
        self.indent = 0

    def emit(self, line: str = ""):
        self.lines.append("    " * self.indent + line)

    def compile(self, program: Program) -> str:
        self.functions = {
            node.name: node for node in program.statements if isinstance(node, FnDef)
        }
        self.emit("#include <stdbool.h>")
        self.emit("#include <stdint.h>")
        self.emit("#include <stdio.h>")
        self.emit("#include <stdlib.h>")
        self.emit()
        self.emit("static void cps_print_string(const char *s) { fputs(s ? s : \"none\", stdout); fputc('\\n', stdout); }")
        self.emit("static void cps_print_i64(long long x) { printf(\"%lld\\n\", x); }")
        self.emit("static void cps_print_f64(double x) { printf(\"%g\\n\", x); }")
        self.emit("static void cps_print_bool(bool x) { puts(x ? \"true\" : \"false\"); }")
        self.emit()
        for fn in self.functions.values():
            self._function(fn)
            self.emit()
        self.emit("int main(void) {")
        self.indent += 1
        # An explicit main() call is a CP+* convenience; native entry is
        # already main, so emitting it would execute user main twice.
        for node in program.statements:
            if isinstance(node, FnDef):
                continue
            if isinstance(node, FnCall) and node.name == "main":
                continue
            self._statement(node)
        if "main" in self.functions:
            self.emit("return cps_main();")
        else:
            self.emit("return 0;")
        self.indent -= 1
        self.emit("}")
        return "\n".join(self.lines) + "\n"

    def _ctype(self, annotation: str) -> str:
        base = (annotation or "auto").split("<", 1)[0]
        return {"int": "long long", "float": "double", "bool": "bool",
                "string": "const char *", "void": "void"}.get(base, "")

    def _function(self, fn: FnDef):
        name = "cps_main" if fn.name == "main" else f"cps_{fn.name}"
        ret = self._ctype(fn.return_type)
        if not ret:
            raise NativeCompileError(
                f"native backend: unsupported return type {fn.return_type!r} "
                f"at line {fn.line}"
            )
        params = []
        for param in fn.params:
            typ = self._ctype(param[1] if len(param) > 1 else "auto")
            if not typ:
                raise NativeCompileError(f"unsupported parameter type at line {fn.line}")
            self.types[param[0]] = typ
            params.append(f"{typ} {param[0]}")
        self.emit(f"{ret} {name}({', '.join(params)}) {{")
        self.indent += 1
        for stmt in fn.body:
            self._statement(stmt)
        if ret == "void":
            self.emit("return;")
        elif ret == "long long":
            self.emit("return 0;")
        elif ret == "double":
            self.emit("return 0.0;")
        elif ret == "bool":
            self.emit("return false;")
        else:
            self.emit("return NULL;")
        self.indent -= 1
        self.emit("}")

    def _statement(self, node: ASTNode):
        if isinstance(node, VarDecl):
            value = self._expr(node.value)
            typ = self._ctype(node.var_type or self.types.get(node.name, "auto"))
            if not typ:
                typ = self._infer_ctype(node.value)
            if not typ:
                raise NativeCompileError(f"cannot infer native type for {node.name} at line {node.line}")
            self.types[node.name] = typ
            self.emit(f"{typ} {node.name} = {value};")
        elif isinstance(node, ReturnStmt):
            self.emit("return;" if node.value is None else f"return {self._expr(node.value)};")
        elif isinstance(node, PipeStmt):
            self._print_call(node.expr)
        elif isinstance(node, FnCall):
            self.emit(f"{self._expr(node)};")
        elif isinstance(node, IfStmt):
            self.emit(f"if ({self._expr(node.condition)}) {{")
            self.indent += 1
            for stmt in node.then_body:
                self._statement(stmt)
            self.indent -= 1
            self.emit("}")
            if node.else_body:
                self.emit("else {")
                self.indent += 1
                for stmt in node.else_body:
                    self._statement(stmt)
                self.indent -= 1
                self.emit("}")
        else:
            raise NativeCompileError(
                f"native backend does not support {node.__class__.__name__} "
                f"at line {getattr(node, 'line', 0)}"
            )

    def _infer_ctype(self, node: ASTNode) -> str:
        if isinstance(node, Literal):
            if isinstance(node.value, bool):
                return "bool"
            if isinstance(node.value, int):
                return "long long"
            if isinstance(node.value, float):
                return "double"
            if isinstance(node.value, str):
                return "const char *"
        if isinstance(node, VarRef):
            return self.types.get(node.name, "")
        if isinstance(node, BinaryOp):
            return "bool" if node.op in {"==", "!=", "<", ">", "<=", ">="} else "long long"
        if isinstance(node, FnCall) and node.name in self.functions:
            return self._ctype(self.functions[node.name].return_type)
        return ""

    def _expr(self, node: ASTNode) -> str:
        if isinstance(node, Literal):
            if node.value is None:
                return "0"
            if isinstance(node.value, bool):
                return "true" if node.value else "false"
            if isinstance(node.value, str):
                return '"' + node.value.replace("\\", "\\\\").replace('"', '\\"') + '"'
            return repr(node.value)
        if isinstance(node, VarRef):
            if node.name not in self.types and node.name not in self.functions:
                raise NativeCompileError(f"unknown native value {node.name} at line {node.line}")
            return node.name if node.name in self.types else f"cps_{node.name}()"
        if isinstance(node, BinaryOp):
            if node.op == "&&" or node.op == "||":
                op = node.op
            else:
                op = node.op
            if node.op in {"+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">=", "&&", "||"}:
                return f"({self._expr(node.left)} {op} {self._expr(node.right)})"
            raise NativeCompileError(f"unsupported native operator {node.op!r}")
        if isinstance(node, FnCall):
            if node.name.startswith("io::"):
                raise NativeCompileError("io::println must be a pipe statement")
            if node.name not in self.functions:
                raise NativeCompileError(f"unknown native function {node.name}")
            return f"cps_{node.name}({', '.join(self._expr(a) for a in node.args)})"
        raise NativeCompileError(
            f"unsupported native expression {node.__class__.__name__} at line {getattr(node, 'line', 0)}"
        )

    def _print_call(self, node: ASTNode):
        if not isinstance(node, FnCall) or node.name != "io::println":
            raise NativeCompileError("native backend supports only io::println in a pipe")
        if not node.args:
            self.emit('puts("");')
            return
        if len(node.args) == 1:
            arg = node.args[0]
            typ = self._infer_ctype(arg)
            if isinstance(arg, Literal) and isinstance(arg.value, str):
                self.emit(f"cps_print_string({self._expr(arg)});")
            elif typ == "const char *":
                self.emit(f"cps_print_string({self._expr(arg)});")
            elif typ == "double":
                self.emit(f"cps_print_f64({self._expr(arg)});")
            elif typ == "bool":
                self.emit(f"cps_print_bool({self._expr(arg)});")
            else:
                self.emit(f"cps_print_i64({self._expr(arg)});")
            return
        if not isinstance(node.args[0], Literal) or not isinstance(node.args[0].value, str):
            raise NativeCompileError("formatted native print needs a literal format string")
        fmt = node.args[0].value
        args = node.args[1:]
        if fmt.count("{}") != len(args):
            raise NativeCompileError("format placeholder count does not match arguments")
        cargs = []
        pieces = fmt.split("{}")
        rendered = ""
        for index, piece in enumerate(pieces):
            rendered += piece.replace("%", "%%")
            if index < len(args):
                typ = self._infer_ctype(args[index])
                if typ == "const char *":
                    rendered += "%s"
                elif typ == "double":
                    rendered += "%g"
                else:
                    rendered += "%lld"
                cargs.append(self._expr(args[index]))
        rendered += "\\n"
        # `rendered` already contains the C escape for the line ending.
        # Escaping backslashes a second time would print the two characters
        # "\\n" instead of a newline.
        escaped = rendered.replace('"', '\\"')
        self.emit(f'printf("{escaped}", {", ".join(cargs)});')


def compile_native(
    program: Program,
    output: str,
    *,
    cc: str = "gcc",
    opt_level: str = "2",
    keep_c: bool = False,
) -> NativeResult:
    """Emit C and compile an executable with the platform C compiler."""
    backend = CBackend()
    source = backend.compile(program)
    output = os.path.abspath(output)
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cpps-native-") as temp:
        c_path = os.path.join(temp, "module.c")
        with open(c_path, "w", encoding="utf-8") as handle:
            handle.write(source)
        command = [cc, "-std=c11", f"-O{opt_level}", c_path, "-o", output]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise NativeCompileError(result.stderr.strip() or "C compiler failed")
        if keep_c:
            with open(output + ".c", "w", encoding="utf-8") as handle:
                handle.write(source)
    return NativeResult(output, source, command)
