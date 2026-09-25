from __future__ import annotations

import ast
from collections import deque

from .python_rules import call_name, is_slow_call


class _FunctionSummaryVisitor(ast.NodeVisitor):
    """Collect direct slow calls and helper calls without nested definitions."""

    def __init__(self) -> None:
        self.direct_slow = False
        self.calls: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Call(self, node: ast.Call) -> None:
        name = call_name(node)
        if is_slow_call(node, name):
            self.direct_slow = True
        if name:
            self.calls.append(name)
        self.generic_visit(node)


class LocalBlockingCatalog:
    """Intra-file helper graph with linear-time reverse blocking propagation."""

    def __init__(self, tree: ast.Module) -> None:
        self._nodes: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self._calls: dict[str, tuple[str, ...]] = {}
        self._blocking: set[str] = set()
        self._collect(tree.body)
        self._summarize()

    def _collect(self, body: list[ast.stmt], prefix: tuple[str, ...] = ()) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = ".".join((*prefix, node.name))
                self._nodes[qualified] = node
                self._collect(node.body, (*prefix, node.name))
            elif isinstance(node, ast.ClassDef):
                self._collect(node.body, (*prefix, node.name))

    def _resolve(self, caller: str, target: str) -> str | None:
        parts = target.split(".") if target else []
        leaf = parts[-1] if parts else ""
        parent = caller.rsplit(".", 1)[0] if "." in caller else ""
        if len(parts) == 2 and parts[0] in {"self", "cls"} and parent:
            candidate = f"{parent}.{leaf}"
            return candidate if candidate in self._nodes else None
        if len(parts) != 1:
            return None
        if target in self._nodes:
            return target
        same_parent = f"{parent}.{leaf}" if parent else leaf
        if same_parent in self._nodes:
            return same_parent
        matches = [name for name in self._nodes if name.rsplit(".", 1)[-1] == leaf]
        return matches[0] if len(matches) == 1 else None

    def _summarize(self) -> None:
        for qualified, node in self._nodes.items():
            visitor = _FunctionSummaryVisitor()
            for stmt in node.body:
                if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    visitor.visit(stmt)
            self._calls[qualified] = tuple(visitor.calls)
            if visitor.direct_slow:
                self._blocking.add(qualified)

        reverse: dict[str, set[str]] = {}
        for caller, calls in self._calls.items():
            for target in calls:
                resolved = self._resolve(caller, target)
                if resolved is not None:
                    reverse.setdefault(resolved, set()).add(caller)

        work = deque(self._blocking)
        while work:
            blocking = work.popleft()
            for caller in reverse.get(blocking, ()):
                if caller in self._blocking:
                    continue
                self._blocking.add(caller)
                work.append(caller)

    def is_blocking_helper(self, caller: str, target: str) -> bool:
        resolved = self._resolve(caller, target)
        return resolved is not None and resolved in self._blocking


__all__ = ["LocalBlockingCatalog"]