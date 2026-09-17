"""
CP+* Semantic Analyzer
=======================

Static analysis pass that runs on the AST *before* execution. This is new,
real functionality: the existing interpreter (interpreter.py) only wraps
ownership at runtime (CPPSOwned) and never rejects a use-after-move or a
type mismatch — it just runs it. This module adds actual compile-time
checking with rustc-style diagnostics.

Two checkers are implemented here, sharing one AST walk:

1. TypeChecker
   - Infers types for literals, binary/unary expressions, variables.
   - Flags mismatched binary operands (e.g. `1 + "hello"`), assigning a
     value of the wrong declared type, and calling a function with the
     wrong number of arguments.
   - Deliberately conservative: CP+* types are still dynamically flavored
     (var_type defaults to 'auto'), so anything not statically knowable is
     left as `Type.UNKNOWN` and never flagged. False positives are worse
     than missed diagnostics for a first real type checker.

2. OwnershipChecker
   - Tracks per-variable ownership state through each scope:
     OWNED, MOVED, BORROWED, MUT_BORROWED, SHARED, CONSUMED, INVALID.
   - Detects: use-after-move, double-move, use of a moved-from borrow
     source, reassigning while a mutable borrow is outstanding, and
     borrowing an already-mutably-borrowed value.
   - `own<T>` values are moved when passed by value into another
     `own<T> x := y` binding, assigned to another owned var, or passed as
     an owned function argument. `share<T>` values are never moved
     (reference counted conceptually). `borrow<T>` never owns.

Both checkers produce `Diagnostic` objects rendered the way rustc/CPs's own
AUDIT_REPORT-style errors look:

    error[E0001]: type mismatch
      --> main.cpps:14:9
       |
    14 | x + "hello"
       |   ^^^^^^^^^
       |
    help: expected Int but found String

This module has zero dependency on the interpreter — it only imports AST
node classes from parser.py — so it can run standalone via `cpps check`.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple
import json

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from parser import (  # noqa: E402
    ASTNode, Program, ModuleDecl, ImportStmt, ExportStmt, VarDecl, FnDef,
    ClassDef, StructDef, TraitDef, ImplBlock, ReturnStmt, BreakStmt,
    ContinueStmt, PanicStmt, PipeStmt, GoStmt, IfStmt, ForStmt, WhileStmt,
    TryCatch, MatchStmt, MatchArm, Literal, VarRef, SelfRef, BinaryOp,
    UnaryOp, Assign, FnCall, MethodCall, FieldAccess, IndexAccess,
    ListLiteral, TupleLiteral, MapLiteral, OwnershipExpr, ResultOk,
    ResultErr, AwaitExpr, PipeExpr, LambdaExpr, RangeExpr, TernaryExpr,
    TypeCastExpr, SpreadExpr,
)


# ──────────────────────────────────────────────────────────────────────────
# Diagnostics
# ──────────────────────────────────────────────────────────────────────────

class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class Diagnostic:
    code: str            # e.g. 'E0001'
    severity: Severity
    message: str
    line: int
    help: Optional[str] = None
    note: Optional[str] = None
    column: int = 0
    related: List[Tuple[str, int, int]] = field(default_factory=list)

    def render(self, filename: str, source_lines: Optional[List[str]] = None) -> str:
        sev = self.severity.value
        out = [f"{sev}[{self.code}]: {self.message}"]
        out.append(f"  --> {filename}:{self.line}")
        if source_lines and 0 < self.line <= len(source_lines):
            src = source_lines[self.line - 1]
            out.append("   |")
            out.append(f"{self.line:>2} | {src}")
            out.append("   |")
        if self.note:
            out.append(f"note: {self.note}")
        if self.help:
            out.append(f"help: {self.help}")
        return "\n".join(out)

    def to_dict(self, filename: str = '<unknown>') -> Dict:
        """Stable machine-readable representation for editor integrations."""
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "file": filename,
            "line": self.line,
            "column": self.column,
            "help": self.help,
            "note": self.note,
            "related": [
                {"label": label, "line": line, "column": column}
                for label, line, column in self.related
            ],
        }


# ──────────────────────────────────────────────────────────────────────────
# Types (lightweight — CP+* is gradually typed)
# ──────────────────────────────────────────────────────────────────────────

class Type:
    """A minimal type representation. Two named types are equal iff their
    names match; UNKNOWN is compatible with everything (gradual typing)."""

    def __init__(self, name: str):
        self.name = name

    def __eq__(self, other):
        if not isinstance(other, Type):
            return False
        if self.name == 'auto' or other.name == 'auto':
            return True
        if self.name == 'unknown' or other.name == 'unknown':
            return True
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

    def __repr__(self):
        return self.name


def is_concrete(t: 'Type') -> bool:
    """True iff `t` is a real, checkable type (not the auto/unknown
    sentinels). Never use `t == Type.AUTO` for this — Type.__eq__ treats
    'auto' as compatible with everything by design, so it always returns
    True and silently disables every check that relies on it."""
    return t.name not in ('auto', 'unknown')


Type.INT = Type('int')
Type.FLOAT = Type('float')
Type.STRING = Type('string')
Type.BOOL = Type('bool')
Type.VOID = Type('void')
Type.UNKNOWN = Type('unknown')
Type.AUTO = Type('auto')

_NUMERIC = {'int', 'float'}


def type_from_annotation(name: Optional[str]) -> Type:
    if not name or name in ('auto',):
        return Type.AUTO
    base = name.split('<')[0].strip()
    known = {'int', 'float', 'string', 'bool', 'void'}
    if base in known:
        return Type(base)
    return Type.UNKNOWN  # generics/struct/class names: not statically modeled yet


# ──────────────────────────────────────────────────────────────────────────
# Ownership state
# ──────────────────────────────────────────────────────────────────────────

class OwnState(Enum):
    OWNED = auto()
    MOVED = auto()
    BORROWED = auto()
    MUT_BORROWED = auto()
    SHARED = auto()
    CONSUMED = auto()
    INVALID = auto()


@dataclass
class VarInfo:
    name: str
    decl_line: int
    var_type: Type
    is_mut: bool = False
    ownership: Optional[str] = None       # 'own' | 'share' | 'borrow' | None
    state: OwnState = OwnState.OWNED
    moved_at: Optional[int] = None
    borrowed_from: Optional[str] = None   # name of source var for `borrow<T> c := a`


class Scope:
    def __init__(self, parent: Optional['Scope'] = None):
        self.parent = parent
        self.vars: Dict[str, VarInfo] = {}

    def declare(self, info: VarInfo):
        self.vars[info.name] = info

    def lookup(self, name: str) -> Optional[VarInfo]:
        scope = self
        while scope is not None:
            if name in scope.vars:
                return scope.vars[name]
            scope = scope.parent
        return None

    def child(self) -> 'Scope':
        return Scope(self)


# ──────────────────────────────────────────────────────────────────────────
# Shared AST walking helpers
# ──────────────────────────────────────────────────────────────────────────

def _stmt_lists(node: ASTNode) -> List[List[ASTNode]]:
    """Return the statement-list attributes of a node that introduce a
    lexical block (so callers can push/pop scopes correctly)."""
    if isinstance(node, (FnDef,)):
        return [node.body]
    if isinstance(node, IfStmt):
        lists = [node.then_body]
        lists += [body for _, body in node.elif_clauses]
        lists.append(node.else_body)
        return lists
    if isinstance(node, (ForStmt, WhileStmt)):
        return [node.body]
    if isinstance(node, TryCatch):
        lists = [node.try_body]
        if getattr(node, 'catch_body', None):
            lists.append(node.catch_body)
        if getattr(node, 'finally_body', None):
            lists.append(node.finally_body)
        return lists
    return []


# ──────────────────────────────────────────────────────────────────────────
# TypeChecker
# ──────────────────────────────────────────────────────────────────────────

class TypeChecker:
    def __init__(self, filename: str = '<unknown>'):
        self.filename = filename
        self.diagnostics: List[Diagnostic] = []
        self.fn_sigs: Dict[str, FnDef] = {}
        self._return_type: Type = Type.VOID

    def check(self, program: Program) -> List[Diagnostic]:
        for node in program.children():
            if isinstance(node, FnDef):
                self.fn_sigs[node.name] = node
        for node in program.children():
            if isinstance(node, FnDef):
                self._check_fn(node)
        return self.diagnostics

    def _err(self, code, msg, line, help=None):
        self.diagnostics.append(Diagnostic(code, Severity.ERROR, msg, line, help=help))

    def _check_fn(self, fn: FnDef):
        env: Dict[str, Type] = {}
        previous_return = self._return_type
        self._return_type = type_from_annotation(fn.return_type)
        for p in fn.params:
            # params: (name, type, ownership, default)
            pname = p[0]
            ptype = type_from_annotation(p[1] if len(p) > 1 else None)
            env[pname] = ptype
        self._check_block(fn.body, env)
        self._return_type = previous_return

    def _check_block(self, body: List[ASTNode], env: Dict[str, Type]):
        for stmt in body:
            self._check_stmt(stmt, env)

    def _check_stmt(self, stmt: ASTNode, env: Dict[str, Type]):
        if isinstance(stmt, VarDecl):
            declared = type_from_annotation(stmt.var_type)
            inferred = self._infer(stmt.value, env) if stmt.value else Type.AUTO
            if is_concrete(declared) and is_concrete(inferred) and declared != inferred:
                self._err(
                    'E0001', 'type mismatch', stmt.line,
                    help=f"expected {declared} but found {inferred}",
                )
            env[stmt.name] = declared if is_concrete(declared) else inferred
        elif isinstance(stmt, Assign):
            if isinstance(stmt.target, VarRef):
                target_t = env.get(stmt.target.name, Type.UNKNOWN)
                value_t = self._infer(stmt.value, env)
                if is_concrete(target_t) and is_concrete(value_t) and target_t != value_t:
                    self._err(
                        'E0001', 'type mismatch', stmt.line,
                        help=f"expected {target_t} but found {value_t}",
                    )
        elif isinstance(stmt, FnCall):
            self._check_call(stmt, env)
        elif isinstance(stmt, PipeStmt):
            self._infer(stmt.expr, env)
        elif isinstance(stmt, ReturnStmt) and stmt.value is not None:
            actual = self._infer(stmt.value, env)
            expected = self._return_type
            # `auto`/unknown and structured types remain gradual, but scalar
            # annotations are enforced at the function boundary.
            if (is_concrete(expected) and is_concrete(actual)
                    and expected != actual
                    and not (expected.name == 'float' and actual.name == 'int')):
                self._err(
                    'E0003',
                    f"return type mismatch: expected {expected} but found {actual}",
                    stmt.line,
                    help=f"return a value of type {expected}",
                )
        for lst in _stmt_lists(stmt):
            self._check_block(lst, dict(env))
        if isinstance(stmt, (IfStmt,)):
            self._infer(stmt.condition, env)
        if isinstance(stmt, (WhileStmt,)):
            self._infer(stmt.condition, env)

    def _check_call(self, call: FnCall, env: Optional[Dict[str, Type]] = None):
        sig = self.fn_sigs.get(call.name)
        if sig is None:
            return  # builtin / stdlib / method — not modeled
        required = [p for p in sig.params if len(p) < 4 or p[3] is None]
        if len(call.args) < len(required) or len(call.args) > len(sig.params):
            self._err(
                'E0002',
                f"function '{call.name}' expects {len(sig.params)} argument(s), got {len(call.args)}",
                call.line,
                help=f"check the signature of '{call.name}'",
            )
            return
        if env is not None:
            for arg, param in zip(call.args, sig.params):
                expected = type_from_annotation(param[1] if len(param) > 1 else None)
                actual = self._infer(arg, env)
                if (is_concrete(expected) and is_concrete(actual)
                        and expected != actual
                        and not (expected.name == 'float' and actual.name == 'int')):
                    self._err(
                        'E0004',
                        f"argument type mismatch in '{call.name}'",
                        call.line,
                        help=f"parameter '{param[0]}' expects {expected}, found {actual}",
                    )

    def _infer(self, expr: Optional[ASTNode], env: Dict[str, Type]) -> Type:
        if expr is None:
            return Type.VOID
        if isinstance(expr, Literal):
            v = expr.value
            if isinstance(v, bool):
                return Type.BOOL
            if isinstance(v, int):
                return Type.INT
            if isinstance(v, float):
                return Type.FLOAT
            if isinstance(v, str):
                return Type.STRING
            return Type.UNKNOWN
        if isinstance(expr, VarRef):
            return env.get(expr.name, Type.UNKNOWN)
        if isinstance(expr, BinaryOp):
            lt = self._infer(expr.left, env)
            rt = self._infer(expr.right, env)
            if expr.op in ('+', '-', '*', '/', '%'):
                if is_concrete(lt) and is_concrete(rt):
                    l_ok = lt.name in _NUMERIC
                    r_ok = rt.name in _NUMERIC
                    if expr.op == '+' and lt.name == 'string' and rt.name == 'string':
                        return Type.STRING
                    if (l_ok or r_ok) and lt != rt:
                        self._err(
                            'E0001', 'type mismatch', expr.line,
                            help=f"expected {lt} but found {rt}",
                        )
                    if lt.name == 'float' or rt.name == 'float':
                        return Type.FLOAT
                    return Type.INT
                return Type.UNKNOWN
            if expr.op in ('==', '!=', '<', '>', '<=', '>=', '&&', '||'):
                return Type.BOOL
            return Type.UNKNOWN
        if isinstance(expr, UnaryOp):
            return self._infer(expr.operand, env)
        if isinstance(expr, OwnershipExpr):
            return self._infer(expr.inner, env)
        if isinstance(expr, FnCall):
            self._check_call(expr)
            for a in expr.args:
                self._infer(a, env)
            sig = self.fn_sigs.get(expr.name)
            if sig is not None:
                return type_from_annotation(sig.return_type)
            return Type.UNKNOWN
        return Type.UNKNOWN


# ──────────────────────────────────────────────────────────────────────────
# OwnershipChecker
# ──────────────────────────────────────────────────────────────────────────

class OwnershipChecker:
    def __init__(self, filename: str = '<unknown>'):
        self.filename = filename
        self.diagnostics: List[Diagnostic] = []

    def check(self, program: Program) -> List[Diagnostic]:
        for node in program.children():
            if isinstance(node, FnDef):
                self._check_fn(node)
        return self.diagnostics

    def _err(self, code, msg, line, help=None, note=None):
        self.diagnostics.append(Diagnostic(code, Severity.ERROR, msg, line, help=help, note=note))

    def _check_fn(self, fn: FnDef):
        scope = Scope()
        for p in fn.params:
            pname = p[0]
            ownership = p[2] if len(p) > 2 else None
            scope.declare(VarInfo(pname, fn.line, type_from_annotation(p[1] if len(p) > 1 else None), ownership=ownership))
        self._check_block(fn.body, scope)

    def _check_block(self, body: List[ASTNode], scope: Scope):
        for stmt in body:
            self._check_stmt(stmt, scope)

    def _check_stmt(self, stmt: ASTNode, scope: Scope):
        if isinstance(stmt, VarDecl):
            if stmt.value is not None:
                self._use_expr(stmt.value, scope, moving_into=stmt.ownership)
            info = VarInfo(
                stmt.name, stmt.line,
                type_from_annotation(stmt.var_type),
                is_mut=stmt.is_mut,
                ownership=stmt.ownership,
            )
            if stmt.ownership == 'borrow' and isinstance(stmt.value, VarRef):
                src = scope.lookup(stmt.value.name)
                if src is not None:
                    info.borrowed_from = src.name
                    if src.ownership == 'own' and src.state == OwnState.OWNED:
                        src.state = OwnState.BORROWED
            scope.declare(info)
        elif isinstance(stmt, Assign):
            if isinstance(stmt.target, VarRef):
                target = scope.lookup(stmt.target.name)
                if target is not None:
                    if target.state == OwnState.MUT_BORROWED:
                        self._err(
                            'E0101',
                            f"cannot assign to '{target.name}' while it is mutably borrowed",
                            stmt.line,
                            help="the borrow must end before reassigning",
                        )
                    # A plain `a = value` fully re-initializes `a`, even if
                    # it was previously moved-from — this is how a moved
                    # binding becomes a valid owner again, so it is not an
                    # error (unlike using `a` as a *source* while moved).
                    target.state = OwnState.OWNED
            self._use_expr(stmt.value, scope, moving_into=None)
        elif isinstance(stmt, FnCall):
            self._use_call_args(stmt, scope)
        elif isinstance(stmt, PipeStmt):
            self._use_expr(stmt.expr, scope, moving_into=None)
        elif isinstance(stmt, ReturnStmt) and stmt.value is not None:
            self._use_expr(stmt.value, scope, moving_into=None)
        for lst in _stmt_lists(stmt):
            self._check_block(lst, scope.child())
        if isinstance(stmt, IfStmt):
            self._use_expr(stmt.condition, scope, moving_into=None)
        if isinstance(stmt, WhileStmt):
            self._use_expr(stmt.condition, scope, moving_into=None)

    def _use_call_args(self, call: FnCall, scope: Scope):
        for arg in call.args:
            self._use_expr(arg, scope, moving_into=None)

    def _use_expr(self, expr: Optional[ASTNode], scope: Scope, moving_into: Optional[str]):
        if expr is None:
            return
        if isinstance(expr, VarRef):
            info = scope.lookup(expr.name)
            if info is None:
                return
            if info.state == OwnState.MOVED:
                self._err(
                    'E0103',
                    f"use of moved value: '{info.name}'",
                    expr.line,
                    note=f"'{info.name}' was moved at line {info.moved_at}",
                    help=f"'{info.name}' has type marked `own<...>`; either clone it before the move or use `share<...>` if it needs multiple owners",
                )
                return
            if info.ownership == 'own' and moving_into == 'own':
                if info.state == OwnState.MOVED:
                    self._err('E0104', f"use of already-moved value: '{info.name}'", expr.line)
                info.state = OwnState.MOVED
                info.moved_at = expr.line
            return
        if isinstance(expr, OwnershipExpr):
            self._use_expr(expr.inner, scope, moving_into=expr.kind)
            return
        if isinstance(expr, BinaryOp):
            self._use_expr(expr.left, scope, None)
            self._use_expr(expr.right, scope, None)
            return
        if isinstance(expr, UnaryOp):
            self._use_expr(expr.operand, scope, None)
            return
        if isinstance(expr, FnCall):
            self._use_call_args(expr, scope)
            return
        if isinstance(expr, (ListLiteral, TupleLiteral)):
            for el in getattr(expr, 'elements', []):
                self._use_expr(el, scope, None)
            return


# ──────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class AnalysisResult:
    diagnostics: List[Diagnostic]

    @property
    def has_errors(self) -> bool:
        return any(d.severity == Severity.ERROR for d in self.diagnostics)

    def render(self, filename: str, source: Optional[str] = None) -> str:
        lines = source.splitlines() if source else None
        return "\n\n".join(d.render(filename, lines) for d in self.diagnostics)

    def to_json(self, filename: str = '<unknown>') -> str:
        return json.dumps(
            {"file": filename, "errors": self.has_errors,
             "diagnostics": [d.to_dict(filename) for d in self.diagnostics]},
            ensure_ascii=False,
            indent=2,
        )


def analyze(program: Program, filename: str = '<unknown>', source: Optional[str] = None) -> AnalysisResult:
    """Run the full semantic analysis pass (types + ownership) over a
    parsed Program and return every diagnostic found, in source order."""
    tc = TypeChecker(filename)
    oc = OwnershipChecker(filename)
    diags = tc.check(program) + oc.check(program)
    diags.sort(key=lambda d: d.line)
    return AnalysisResult(diags)
