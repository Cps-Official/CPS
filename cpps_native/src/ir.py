"""Typed intermediate representation for CP+*.

The interpreter remains the reference execution engine, while this module
provides a deliberately small but real compiler IR.  The IR is SSA-shaped
inside a basic block: values have names, instructions have explicit result
types, and control-flow terminators are verified before a backend consumes it.

The lowering is intentionally strict.  It is better to reject a construct
that has no lowering rule than to print an attractive but meaningless IR.
This makes ``cpps --ir`` useful for compiler development and gives the native
backend a trustworthy input contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from parser import (
    ASTNode, Assign, BinaryOp, FnCall, FnDef, IfStmt, Literal, PipeStmt,
    Program, ReturnStmt, VarDecl, VarRef,
)


class IRLoweringError(Exception):
    """Raised when an AST construct has no safe IR lowering."""


@dataclass(frozen=True)
class IRType:
    name: str

    def __str__(self) -> str:
        return self.name


I32 = IRType("i32")
I64 = IRType("i64")
F64 = IRType("f64")
BOOL = IRType("bool")
STRING = IRType("string")
VOID = IRType("void")
UNKNOWN = IRType("unknown")


@dataclass
class IRInstruction:
    opcode: str
    result: Optional[str] = None
    type: IRType = VOID
    operands: List[str] = field(default_factory=list)
    attrs: Dict[str, Any] = field(default_factory=dict)
    line: int = 0

    @property
    def is_terminator(self) -> bool:
        return self.opcode in {"ret", "br", "condbr", "unreachable"}

    def format(self) -> str:
        prefix = f"{self.result}:{self.type} = " if self.result else ""
        args = ", ".join(self.operands)
        attrs = ""
        if self.attrs:
            rendered = ", ".join(
                f"{k}={v!r}" for k, v in sorted(self.attrs.items())
            )
            attrs = f" {{{rendered}}}"
        return f"  {prefix}{self.opcode} {args}{attrs}".rstrip()


@dataclass
class BasicBlock:
    name: str
    instructions: List[IRInstruction] = field(default_factory=list)

    def append(self, instruction: IRInstruction) -> IRInstruction:
        if self.instructions and self.instructions[-1].is_terminator:
            raise IRLoweringError(
                f"cannot append after terminator in block {self.name}"
            )
        self.instructions.append(instruction)
        return instruction

    @property
    def terminator(self) -> Optional[IRInstruction]:
        if self.instructions and self.instructions[-1].is_terminator:
            return self.instructions[-1]
        return None


@dataclass
class IRFunction:
    name: str
    params: List[Tuple[str, IRType]] = field(default_factory=list)
    return_type: IRType = VOID
    blocks: List[BasicBlock] = field(default_factory=list)
    attrs: Dict[str, Any] = field(default_factory=dict)

    def entry(self) -> BasicBlock:
        if not self.blocks:
            self.blocks.append(BasicBlock("entry"))
        return self.blocks[0]


@dataclass
class IRModule:
    name: str = "module"
    functions: List[IRFunction] = field(default_factory=list)
    globals: Dict[str, Tuple[IRType, Any]] = field(default_factory=dict)

    def format(self) -> str:
        out = [f"module {self.name}"]
        for name, (typ, value) in self.globals.items():
            out.append(f"global @{name}:{typ} = {value!r}")
        for fn in self.functions:
            params = ", ".join(f"%{n}:{t}" for n, t in fn.params)
            out.append(f"\nfn @{fn.name}({params}) -> {fn.return_type} {{")
            for block in fn.blocks:
                out.append(f"{block.name}:")
                out.extend(inst.format() for inst in block.instructions)
            out.append("}")
        return "\n".join(out)


class IRBuilder:
    """Stateful builder with monotonically unique SSA names and blocks."""

    def __init__(self, function: IRFunction):
        self.function = function
        self.block = function.entry()
        self._value_id = 0
        self._block_id = 0

    def value(self, prefix: str = "v") -> str:
        self._value_id += 1
        return f"%{prefix}{self._value_id}"

    def block_name(self, prefix: str = "block") -> str:
        self._block_id += 1
        return f"{prefix}{self._block_id}"

    def emit(
        self, opcode: str, typ: IRType = VOID, operands: Iterable[str] = (),
        *, attrs: Optional[Dict[str, Any]] = None, line: int = 0,
        result: bool = True,
    ) -> Optional[str]:
        name = self.value(opcode) if result and typ != VOID else None
        self.block.append(IRInstruction(
            opcode, name, typ, list(operands), attrs or {}, line
        ))
        return name

    def terminate(self, opcode: str, operands: Iterable[str] = (), line: int = 0):
        self.block.append(IRInstruction(opcode, None, VOID, list(operands), {}, line))

    def new_block(self, prefix: str = "block") -> BasicBlock:
        block = BasicBlock(self.block_name(prefix))
        self.function.blocks.append(block)
        self.block = block
        return block


def _literal_type(value: Any) -> IRType:
    if isinstance(value, bool):
        return BOOL
    if isinstance(value, int):
        return I64
    if isinstance(value, float):
        return F64
    if isinstance(value, str):
        return STRING
    if value is None:
        return VOID
    return UNKNOWN


class IRLowerer:
    """Lower the AST subset shared by the interpreter and native backend."""

    def __init__(self, module_name: str = "main"):
        self.module = IRModule(module_name)
        self._env: Dict[str, Tuple[str, IRType]] = {}
        self._functions: Dict[str, IRFunction] = {}
        self._builder: Optional[IRBuilder] = None

    def lower(self, program: Program) -> IRModule:
        for node in program.statements:
            if isinstance(node, FnDef):
                self._lower_function(node)
        top_level = [
            n for n in program.statements
            if not isinstance(n, FnDef)
        ]
        if top_level:
            script = IRFunction("__script", [], VOID)
            self.module.functions.insert(0, script)
            self._start(script)
            for node in top_level:
                self._statement(node)
            if not self._builder.block.terminator:
                self._builder.terminate("ret", ["void"])
        self.verify(self.module)
        return self.module

    def _start(self, fn: IRFunction):
        self._builder = IRBuilder(fn)
        self._env = {name: (f"%{name}", typ) for name, typ in fn.params}

    def _lower_function(self, node: FnDef):
        params = [
            (p[0], self._type_name(p[1] if len(p) > 1 else "auto"))
            for p in node.params
        ]
        fn = IRFunction(node.name, params, self._type_name(node.return_type))
        self.module.functions.append(fn)
        self._functions[node.name] = fn
        self._start(fn)
        for stmt in node.body:
            self._statement(stmt)
        if not self._builder.block.terminator:
            self._builder.terminate(
                "ret", ["void" if fn.return_type == VOID else "zero"],
                line=node.line,
            )

    @staticmethod
    def _type_name(name: Optional[str]) -> IRType:
        if not name or name == "auto":
            return UNKNOWN
        base = name.split("<", 1)[0].strip()
        return {
            "int": I64, "float": F64, "bool": BOOL,
            "string": STRING, "void": VOID,
        }.get(base, UNKNOWN)

    def _literal(self, node: Literal) -> str:
        typ = _literal_type(node.value)
        value = repr(node.value)
        return self._builder.emit(
            "const", typ, [], attrs={"value": node.value}, line=node.line
        ) or value

    def _expr(self, node: ASTNode) -> Tuple[str, IRType]:
        if isinstance(node, Literal):
            return self._literal(node), _literal_type(node.value)
        if isinstance(node, VarRef):
            if node.name not in self._env:
                raise IRLoweringError(f"unknown value {node.name} at line {node.line}")
            return self._env[node.name]
        if isinstance(node, BinaryOp):
            left, lt = self._expr(node.left)
            right, rt = self._expr(node.right)
            typ = BOOL if node.op in {
                "==", "!=", "<", ">", "<=", ">=", "&&", "||"
            } else (F64 if F64 in (lt, rt) else lt)
            value = self._builder.emit(
                "binop", typ, [left, right],
                attrs={"op": node.op}, line=node.line,
            )
            return value or "void", typ
        if isinstance(node, FnCall):
            args = [self._expr(a)[0] for a in node.args]
            result_type = (
                self._functions[node.name].return_type
                if node.name in self._functions else UNKNOWN
            )
            value = self._builder.emit(
                "call", result_type, args,
                attrs={"name": node.name}, line=node.line,
                result=result_type != VOID,
            )
            return value or "void", result_type
        raise IRLoweringError(
            f"no IR expression lowering for {node.__class__.__name__}"
        )

    def _statement(self, node: ASTNode):
        if isinstance(node, VarDecl):
            value, typ = self._expr(node.value)
            slot = self._builder.emit(
                "alloca", typ, [], attrs={"name": node.name}, line=node.line
            )
            self._builder.emit("store", VOID, [slot or node.name, value],
                               line=node.line, result=False)
            self._env[node.name] = (slot or f"%{node.name}", typ)
            return
        if isinstance(node, Assign):
            if not isinstance(node.target, VarRef):
                raise IRLoweringError("IR assignment target must be a variable")
            value, typ = self._expr(node.value)
            target = self._env.get(node.target.name)
            if target is None:
                raise IRLoweringError(f"unknown assignment target {node.target.name}")
            self._builder.emit(
                "store", VOID, [target[0], value],
                attrs={"op": node.op}, line=node.line, result=False,
            )
            return
        if isinstance(node, ReturnStmt):
            if node.value is None:
                self._builder.terminate("ret", ["void"], node.line)
            else:
                value, _ = self._expr(node.value)
                self._builder.terminate("ret", [value], node.line)
            return
        if isinstance(node, PipeStmt):
            self._expr(node.expr)
            return
        if isinstance(node, FnCall):
            self._expr(node)
            return
        if isinstance(node, IfStmt):
            cond, _ = self._expr(node.condition)
            then_block = self._builder.new_block("then")
            merge = BasicBlock(self._builder.block_name("merge"))
            self._builder.function.blocks.append(merge)
            # The conditional branch is emitted in the block that preceded
            # then_block by moving it back for a single well-formed CFG edge.
            predecessor = self._builder.function.blocks[-3]
            self._builder.block = predecessor
            self._builder.terminate("condbr", [cond, then_block.name, merge.name], node.line)
            self._builder.block = then_block
            for stmt in node.then_body:
                self._statement(stmt)
            if not self._builder.block.terminator:
                self._builder.terminate("br", [merge.name], node.line)
            self._builder.block = merge
            return
        raise IRLoweringError(
            f"no IR statement lowering for {node.__class__.__name__}"
        )

    @staticmethod
    def verify(module: IRModule):
        """Verify terminators, unique definitions and branch destinations."""
        for fn in module.functions:
            if not fn.blocks:
                raise IRLoweringError(f"function {fn.name} has no blocks")
            names = {b.name for b in fn.blocks}
            definitions = {f"%{name}" for name, _ in fn.params}
            for block in fn.blocks:
                if not block.terminator:
                    raise IRLoweringError(f"block {block.name} has no terminator")
                terminated = False
                for instruction in block.instructions:
                    if terminated:
                        raise IRLoweringError(
                            f"instruction after terminator in {block.name}"
                        )
                    if instruction.result:
                        if instruction.result in definitions:
                            raise IRLoweringError(
                                f"duplicate SSA definition {instruction.result}"
                            )
                        definitions.add(instruction.result)
                    terminated = instruction.is_terminator
                    if instruction.opcode in {"br", "condbr"}:
                        targets = (
                            instruction.operands[1:]
                            if instruction.opcode == "condbr"
                            else instruction.operands
                        )
                        for target in targets:
                            if target not in names:
                                raise IRLoweringError(
                                    f"branch to missing block {target}"
                                )


def lower(program: Program, module_name: str = "main") -> IRModule:
    """Public lowering entry point."""
    return IRLowerer(module_name).lower(program)
