from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .source_index import source_nodes, source_text


@dataclass(frozen=True, slots=True)
class ModuleHotspot:
    module: str
    path: str
    physical_lines: int
    functions: int
    classes: int
    imports: int
    branches: int
    exception_handlers: int
    max_function_lines: int
    score: int


def analyze_hotspots(root: Path, package_roots: tuple[str, ...] = ("noetrium_platform", "projects")) -> tuple[ModuleHotspot, ...]:
    rows = []
    branch_types = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match, ast.IfExp)
    for pkg in package_roots:
        base = root / pkg
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            text = source_text(path)
            nodes = source_nodes(path)
            functions = classes = imports = branches = handlers = max_fn = 0
            for node in nodes:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions += 1
                    max_fn = max(max_fn, getattr(node, "end_lineno", node.lineno) - node.lineno + 1)
                elif isinstance(node, ast.ClassDef):
                    classes += 1
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    imports += 1
                if isinstance(node, branch_types):
                    branches += 1
                if isinstance(node, ast.ExceptHandler):
                    handlers += 1
            lines = len(text.splitlines())
            module = ".".join(path.relative_to(root).with_suffix("").parts).replace(".__init__", "")
            score = lines + branches * 8 + imports * 3 + handlers * 10 + max(0, max_fn - 50) * 2
            rows.append(ModuleHotspot(module, path.relative_to(root).as_posix(), lines, functions, classes, imports, branches, handlers, max_fn, score))
    return tuple(sorted(rows, key=lambda row: (-row.score, row.module)))
