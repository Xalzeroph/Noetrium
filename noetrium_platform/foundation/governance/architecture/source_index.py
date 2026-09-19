from __future__ import annotations

"""Bounded per-report source cache for focused architecture invariant scans.

Whole-repository architecture facts are produced by ``source_profile`` in one
streaming AST pass.  Source invariants still need arbitrary syntax trees for
small, overlapping subsets of files; this bounded LRU avoids reparsing nearby
files without retaining the repository's entire AST forest in memory.
"""

import ast
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from noetrium_platform.foundation.governance.api import RepositorySourceIndexPort


@dataclass(slots=True)
class ArchitectureSourceIndex:
    root: Path
    max_entries: int = 96
    repository_index: RepositorySourceIndexPort | None = None
    _texts: OrderedDict[Path, str] = field(default_factory=OrderedDict)
    _trees: OrderedDict[Path, ast.AST] = field(default_factory=OrderedDict)
    _imports: dict[Path, tuple[tuple[str, int], ...]] = field(default_factory=dict)
    _import_edge_sets: dict[tuple[str, ...], tuple[object, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()
        if self.max_entries < 1:
            raise ValueError("max_entries must be >= 1")

    @staticmethod
    def _key(path: Path) -> Path:
        return Path(path)

    def _relative(self, path: Path) -> str:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate.relative_to(self.root).as_posix()
        return candidate.as_posix()

    @staticmethod
    def _touch(cache: OrderedDict, key):
        value = cache.pop(key)
        cache[key] = value
        return value

    def _trim(self) -> None:
        while len(self._trees) > self.max_entries:
            key, _ = self._trees.popitem(last=False)
            self._texts.pop(key, None)
        while len(self._texts) > self.max_entries:
            self._texts.popitem(last=False)

    @staticmethod
    def _is_excluded_source_path(path: Path) -> bool:
        return any(
            part.startswith(".rsync-") or part in {
                "__pycache__", ".git", ".venv", "venv", "node_modules",
                ".pytest_cache", ".local", ".server-state", "build", "dist",
            }
            for part in path.parts
        )

    def text(self, path: Path) -> str:
        key = self._key(path)
        if self._is_excluded_source_path(key):
            return ""
        if key in self._texts:
            return self._touch(self._texts, key)
        text = (
            self.repository_index.text(self._relative(key))
            if self.repository_index is not None
            else key.read_text(encoding="utf-8")
        )
        self._texts[key] = text
        self._trim()
        return text

    def tree(self, path: Path) -> ast.AST:
        key = self._key(path)
        if self._is_excluded_source_path(key):
            return ast.parse("", filename=str(key))
        if key in self._trees:
            return self._touch(self._trees, key)
        tree = (
            self.repository_index.python_tree(self._relative(key))
            if self.repository_index is not None
            else ast.parse(self.text(key), filename=str(key))
        )
        self._trees[key] = tree
        self._trim()
        return tree

    def nodes(self, path: Path) -> tuple[ast.AST, ...]:
        # ast.walk is cheap relative to parse and the tuple itself can be large;
        # return a transient view rather than duplicating every node reference in
        # a second repository-sized cache.
        return tuple(ast.walk(self.tree(self._key(path))))



    def seed_import_edges(self, package_roots: tuple[str, ...], edges) -> None:
        self._import_edge_sets[tuple(package_roots)] = tuple(edges)

    def import_edges(self, package_roots: tuple[str, ...]):
        return self._import_edge_sets.get(tuple(package_roots))

    def seed_imports(self, rows) -> None:
        """Seed compact import facts without retaining syntax trees."""
        for path, imports in rows:
            self._imports[self._key(Path(path))] = tuple(imports)

    def imports(self, path: Path) -> tuple[tuple[str, int], ...]:
        key = self._key(path)
        cached = self._imports.get(key)
        if cached is not None:
            return cached
        tree = self.tree(key)
        rows: list[tuple[str, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                rows.append((node.module or "", node.lineno))
            elif isinstance(node, ast.Import):
                rows.extend((alias.name, node.lineno) for alias in node.names)
        value = tuple(rows)
        self._imports[key] = value
        return value

    @property
    def cached_texts(self) -> int:
        return len(self._texts)

    @property
    def cached_trees(self) -> int:
        return len(self._trees)


_ACTIVE_INDEX: ContextVar[ArchitectureSourceIndex | None] = ContextVar(
    "architecture_source_index",
    default=None,
)


@contextmanager
def architecture_source_index(
    root: Path,
    *,
    max_entries: int = 96,
    repository_index: RepositorySourceIndexPort | None = None,
) -> Iterator[ArchitectureSourceIndex]:
    index = ArchitectureSourceIndex(root, max_entries=max_entries, repository_index=repository_index)
    token = _ACTIVE_INDEX.set(index)
    try:
        yield index
    finally:
        _ACTIVE_INDEX.reset(token)


def cached_import_edges(package_roots: tuple[str, ...]):
    index = _ACTIVE_INDEX.get()
    return None if index is None else index.import_edges(tuple(package_roots))

def source_imports(path: Path) -> tuple[tuple[str, int], ...]:
    index = _ACTIVE_INDEX.get()
    if index is None:
        path = Path(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rows: list[tuple[str, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                rows.append((node.module or "", node.lineno))
            elif isinstance(node, ast.Import):
                rows.extend((alias.name, node.lineno) for alias in node.names)
        return tuple(rows)
    return index.imports(Path(path))

def source_text(path: Path) -> str:
    index = _ACTIVE_INDEX.get()
    if index is None:
        return Path(path).read_text(encoding="utf-8")
    return index.text(Path(path))


def source_tree(path: Path) -> ast.AST:
    index = _ACTIVE_INDEX.get()
    if index is None:
        path = Path(path)
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return index.tree(Path(path))


def source_nodes(path: Path) -> tuple[ast.AST, ...]:
    index = _ACTIVE_INDEX.get()
    if index is None:
        return tuple(ast.walk(source_tree(Path(path))))
    return index.nodes(Path(path))


__all__ = [
    "ArchitectureSourceIndex",
    "architecture_source_index",
    "cached_import_edges",
    "source_imports",
    "source_nodes",
    "source_text",
    "source_tree",
]
