"""Local, reproducible CP+* package manifest and lock resolution.

Networking and registry credentials do not belong in the compiler process.
The package layer therefore resolves a manifest against explicit local roots,
records content hashes, and emits a deterministic lock representation.  A
future registry client can implement the same resolver interface without
changing the compiler or interpreter.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


class PackageError(Exception):
    pass


@dataclass(frozen=True)
class Dependency:
    name: str
    requirement: str = "*"
    source: Optional[str] = None


@dataclass
class Manifest:
    name: str
    version: str
    entry: str = "src/main.cpps"
    dependencies: List[Dependency] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "package": {"name": self.name, "version": self.version,
                        "entry": self.entry},
            "dependencies": {
                dep.name: dep.requirement for dep in sorted(
                    self.dependencies, key=lambda item: item.name
                )
            },
        }


@dataclass(frozen=True)
class LockedDependency:
    name: str
    version: str
    path: str
    sha256: str

    def to_dict(self) -> Dict:
        return {"name": self.name, "version": self.version,
                "path": self.path, "sha256": self.sha256}


@dataclass
class LockFile:
    package: str
    dependencies: List[LockedDependency]

    def dumps(self) -> str:
        return json.dumps(
            {"package": self.package,
             "dependencies": [d.to_dict() for d in self.dependencies]},
            ensure_ascii=False, indent=2, sort_keys=True,
        ) + "\n"


def load_manifest(path: str) -> Manifest:
    try:
        import tomllib
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, ValueError) as exc:
        raise PackageError(f"cannot read manifest {path}: {exc}") from exc
    package = data.get("package", {})
    if not package.get("name") or not package.get("version"):
        raise PackageError("manifest requires [package].name and .version")
    raw = data.get("dependencies", {})
    dependencies = []
    for name, value in sorted(raw.items()):
        if isinstance(value, str):
            dependencies.append(Dependency(name, value))
        elif isinstance(value, dict):
            dependencies.append(Dependency(
                name, value.get("version", "*"), value.get("path")
            ))
        else:
            raise PackageError(f"invalid dependency declaration for {name}")
    return Manifest(
        package["name"], package["version"],
        package.get("entry", "src/main.cpps"), dependencies
    )


class PackageResolver:
    """Resolve path dependencies and local package roots deterministically."""

    def __init__(self, roots: Optional[Iterable[str]] = None):
        self.roots = [os.path.abspath(root) for root in (roots or [os.getcwd()])]

    def resolve(self, manifest: Manifest) -> LockFile:
        locked = []
        for dep in sorted(manifest.dependencies, key=lambda item: item.name):
            path = self._find(dep)
            version = self._read_version(path, dep)
            if not self._satisfies(version, dep.requirement):
                raise PackageError(
                    f"{dep.name} resolved to {version}, "
                    f"which does not satisfy {dep.requirement}"
                )
            locked.append(LockedDependency(
                dep.name, version, path, self._tree_hash(path)
            ))
        return LockFile(manifest.name, locked)

    def _find(self, dep: Dependency) -> str:
        candidates = []
        if dep.source:
            candidates.append(os.path.abspath(dep.source))
        for root in self.roots:
            candidates.extend([
                os.path.join(root, dep.name),
                os.path.join(root, f"{dep.name}.cpps"),
            ])
        for candidate in candidates:
            if os.path.exists(candidate):
                return os.path.realpath(candidate)
        raise PackageError(f"dependency '{dep.name}' not found in package roots")

    @staticmethod
    def _read_version(path: str, dep: Dependency) -> str:
        manifest = os.path.join(path, "cp.toml") if os.path.isdir(path) else None
        if manifest and os.path.isfile(manifest):
            return load_manifest(manifest).version
        exact = re.fullmatch(r"=\s*([0-9]+(?:\.[0-9]+){0,2})", dep.requirement)
        return exact.group(1) if exact else "0.0.0"

    @staticmethod
    def _satisfies(version: str, requirement: str) -> bool:
        if requirement in ("", "*", "latest"):
            return True
        match = re.fullmatch(r"=\s*([0-9]+(?:\.[0-9]+){0,2})", requirement)
        return not match or version == match.group(1)

    @staticmethod
    def _tree_hash(path: str) -> str:
        digest = hashlib.sha256()
        files = []
        if os.path.isfile(path):
            files = [path]
        else:
            for root, dirs, names in os.walk(path):
                dirs[:] = sorted(d for d in dirs if d not in {".git", "__pycache__"})
                for name in sorted(names):
                    files.append(os.path.join(root, name))
        for filename in files:
            rel = os.path.relpath(filename, path if os.path.isdir(path) else os.path.dirname(path))
            digest.update(rel.encode("utf-8"))
            with open(filename, "rb") as handle:
                digest.update(handle.read())
        return digest.hexdigest()
