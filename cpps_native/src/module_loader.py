"""Filesystem module discovery and deterministic import loading.

The interpreter historically loaded imports relative to the process working
directory and silently ignored failures.  This loader gives the toolchain a
single resolver with search roots, a cache, canonical paths and explicit
circular-dependency diagnostics.  Execution remains owned by the interpreter;
the loader only parses and resolves source modules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from lexer import tokenize
from parser import ImportStmt, Parser, Program


class ModuleError(Exception):
    def __init__(self, message: str, chain: Optional[List[str]] = None):
        self.chain = chain or []
        suffix = f" ({' -> '.join(self.chain)})" if self.chain else ""
        super().__init__(message + suffix)


@dataclass
class Module:
    name: str
    path: str
    source: str
    ast: Program
    imports: List[str] = field(default_factory=list)


class ModuleLoader:
    """Resolve module names such as ``app::math`` to ``app/math.cpps``."""

    def __init__(self, roots: Optional[List[str]] = None):
        self.roots = [os.path.abspath(r) for r in (roots or [os.getcwd()])]
        self.cache: Dict[str, Module] = {}
        self._loading: List[str] = []

    @staticmethod
    def module_name(path: str, root: str) -> str:
        rel = os.path.relpath(path, root)
        if rel.endswith(".cpps"):
            rel = rel[:-5]
        return rel.replace(os.sep, "::")

    def resolve(self, name: str, from_path: Optional[str] = None) -> str:
        normalized = name.replace("::", os.sep).replace(".", os.sep)
        candidates: List[str] = []
        if from_path:
            base = os.path.dirname(os.path.abspath(from_path))
            candidates.append(os.path.join(base, normalized + ".cpps"))
            candidates.append(os.path.join(base, normalized, "mod.cpps"))
        for root in self.roots:
            candidates.append(os.path.join(root, normalized + ".cpps"))
            candidates.append(os.path.join(root, normalized, "mod.cpps"))
        for candidate in candidates:
            if os.path.isfile(candidate):
                return os.path.realpath(candidate)
        raise ModuleError(f"module '{name}' not found")

    def load(self, name: str, from_path: Optional[str] = None) -> Module:
        path = self.resolve(name, from_path)
        if path in self._loading:
            chain = self._loading[self._loading.index(path):] + [path]
            raise ModuleError("circular module dependency", chain)
        if path in self.cache:
            return self.cache[path]
        self._loading.append(path)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
            tokens = tokenize(source, path)
            parser = Parser(tokens, path)
            ast = parser.parse()
            if parser.errors:
                raise ModuleError(
                    f"module '{name}' contains {len(parser.errors)} parse error(s)"
                )
            imports = [
                "::".join(stmt.module)
                for stmt in ast.statements if isinstance(stmt, ImportStmt)
            ]
            module = Module(name, path, source, ast, imports)
            self.cache[path] = module
            # Resolve all edges now so dependency failures happen before any
            # module executes and cache order is deterministic.
            for imported in imports:
                if not imported.startswith("std::"):
                    self.load(imported, path)
            return module
        finally:
            self._loading.pop()

    def dependency_order(self, entry: str) -> List[Module]:
        result: List[Module] = []
        seen = set()

        def visit(module: Module):
            if module.path in seen:
                return
            seen.add(module.path)
            for imported in module.imports:
                if not imported.startswith("std::"):
                    visit(self.load(imported, module.path))
            result.append(module)

        visit(self.load(entry))
        return result
