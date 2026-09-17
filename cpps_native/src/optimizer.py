"""Optimization passes for the CP+* IR.

Passes mutate only verified IR and return a small report.  The current
pipeline is intentionally conservative: constant folding and unreachable
block removal are semantics-preserving for the scalar IR, while the pass
manager makes it straightforward to add target-specific passes later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from ir import IRInstruction, IRModule, IRType, IRLoweringError


@dataclass
class PassReport:
    name: str
    changed: int = 0
    removed: int = 0
    notes: List[str] = field(default_factory=list)


class ConstantFolder:
    name = "constant-folding"

    def run(self, module: IRModule) -> PassReport:
        report = PassReport(self.name)
        for fn in module.functions:
            constants: Dict[str, Any] = {}
            for block in fn.blocks:
                for inst in block.instructions:
                    if inst.opcode == "const" and inst.result:
                        constants[inst.result] = inst.attrs.get("value")
                    elif inst.opcode == "binop" and inst.result:
                        op = inst.attrs.get("op")
                        args = [constants.get(a, _MISSING) for a in inst.operands]
                        if _MISSING not in args and op in _OPS:
                            try:
                                value = _OPS[op](*args)
                            except (ArithmeticError, TypeError):
                                continue
                            inst.opcode = "const"
                            inst.operands = []
                            inst.attrs = {"value": value}
                            constants[inst.result] = value
                            report.changed += 1
        return report


class DeadBlockEliminator:
    name = "dead-block-elimination"

    def run(self, module: IRModule) -> PassReport:
        report = PassReport(self.name)
        for fn in module.functions:
            if not fn.blocks:
                continue
            by_name = {b.name: b for b in fn.blocks}
            reachable: Set[str] = set()
            work = [fn.blocks[0].name]
            while work:
                name = work.pop()
                if name in reachable:
                    continue
                reachable.add(name)
                block = by_name[name]
                term = block.terminator
                if term and term.opcode == "br":
                    work.extend(term.operands)
                elif term and term.opcode == "condbr":
                    work.extend(term.operands[1:])
            old = len(fn.blocks)
            fn.blocks[:] = [b for b in fn.blocks if b.name in reachable]
            report.removed += old - len(fn.blocks)
        return report


class PassManager:
    def __init__(self, passes=None):
        self.passes = list(passes or [ConstantFolder(), DeadBlockEliminator()])

    def run(self, module: IRModule) -> List[PassReport]:
        from ir import IRLowerer
        reports = []
        IRLowerer.verify(module)
        for compiler_pass in self.passes:
            report = compiler_pass.run(module)
            IRLowerer.verify(module)
            reports.append(report)
        return reports


_MISSING = object()
_OPS = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a / b,
    "%": lambda a, b: a % b,
    "**": lambda a, b: a ** b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
}
