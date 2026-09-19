from __future__ import annotations

import ast
from dataclasses import replace

from noetrium_platform.foundation.governance.api import RepositorySourceIndexPort
from noetrium_platform.foundation.governance.algorithm.api import (
    AlgorithmLanguage,
    AlgorithmMetrics,
    AlgorithmSymbol,
    FileAnalysis,
    SourceDocument,
)
from .scoring import estimated_complexity, score_metrics


_DB_COMPONENTS = {"execute", "executemany", "cursor", "commit", "rollback", "fetchone", "fetchall"}
_IO_COMPONENTS = {"open", "read", "read_bytes", "read_text", "write", "write_bytes", "write_text", "send", "recv", "request", "urlopen"}
_SERIALIZATION_COMPONENTS = {"dumps", "dump", "loads", "load", "encode", "decode", "serialize", "deserialize"}
_LOCK_COMPONENTS = {"acquire", "wait", "lock", "locked"}
_SUBPROCESS_COMPONENTS = {"run", "popen", "check_call", "check_output", "call"}
_SORT_COMPONENTS = {"sort", "sorted", "nsmallest", "nlargest"}


_SUPPORTED_COMPLEXITY_CONTRACTS = {"O(1)", "O(N)", "O(N log N)", "O(N^2)", "O(N^3+)"}

def _complexity_contract(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str | None, str | None]:
    doc = ast.get_docstring(node, clean=False) or ""
    declared = None
    rationale = None
    for raw_line in doc.splitlines():
        line = raw_line.strip()
        if line.startswith("Algorithm-Complexity:"):
            candidate = line.split(":", 1)[1].strip()
            if candidate in _SUPPORTED_COMPLEXITY_CONTRACTS:
                declared = candidate
        elif line.startswith("Algorithm-Rationale:"):
            candidate = line.split(":", 1)[1].strip()
            if len(candidate) >= 20:
                rationale = candidate
    if declared is None or rationale is None:
        return None, None
    return declared, rationale


def _call_path(node: ast.Call) -> tuple[str, ...]:
    parts: list[str] = []
    current: ast.AST = node.func
    while isinstance(current, ast.Attribute):
        parts.append(current.attr.lower())
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id.lower())
    return tuple(reversed(parts))


class _FunctionMetricsVisitor(ast.NodeVisitor):
    def __init__(self, symbol_name: str) -> None:
        self.symbol_name = symbol_name
        self.branches = 0
        self.loops = 0
        self.max_loop_depth = 0
        self._loop_depth = 0
        self.unbounded_loops = 0
        self._bounded_names: set[str] = set()
        self.comprehensions = 0
        self.sort_calls = 0
        self.unbounded_sort_calls = 0
        self.database_calls_in_loops = 0
        self.io_calls_in_loops = 0
        self.serialization_calls_in_loops = 0
        self.lock_calls_in_loops = 0
        self.subprocess_calls_in_loops = 0
        self.recursive_calls = 0
        self.call_count = 0

    @staticmethod
    def _assigned_names(node: ast.AST) -> tuple[str, ...]:
        if isinstance(node, ast.Name):
            return (node.id,)
        if isinstance(node, (ast.Tuple, ast.List)):
            return tuple(name for child in node.elts for name in _FunctionMetricsVisitor._assigned_names(child))
        return ()

    def _is_statically_bounded(self, node: ast.AST) -> bool:
        """Return true only when iterable cardinality is source-bounded, not input-bounded.

        This is intentionally conservative. Unknown calls/names remain unbounded. A
        bounded comprehension may compute arbitrary values; only its generator
        cardinalities matter for the result-size upper bound.
        """
        if isinstance(node, (ast.Tuple, ast.List, ast.Set, ast.Dict)):
            return True
        if isinstance(node, ast.Name):
            return node.id in self._bounded_names
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            return all(self._is_statically_bounded(generator.iter) for generator in node.generators)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id == "range":
                    return bool(node.args) and all(isinstance(arg, ast.Constant) and type(arg.value) is int for arg in node.args)
                if node.func.id in {"sorted", "list", "tuple", "set", "frozenset", "reversed", "enumerate"}:
                    return len(node.args) == 1 and self._is_statically_bounded(node.args[0])
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"keys", "values", "items"}:
                return not node.args and not node.keywords and self._is_statically_bounded(node.func.value)
        return False

    @staticmethod
    def _mutated_container_name(node: ast.AST) -> str | None:
        current = node
        while isinstance(current, (ast.Subscript, ast.Attribute)):
            current = current.value
        return current.id if isinstance(current, ast.Name) else None

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        bounded = self._is_statically_bounded(node.value)
        for target in node.targets:
            names = self._assigned_names(target)
            if names:
                for name in names:
                    if bounded:
                        self._bounded_names.add(name)
                    else:
                        self._bounded_names.discard(name)
            else:
                mutated = self._mutated_container_name(target)
                if mutated is not None:
                    self._bounded_names.discard(mutated)
            self.visit(target)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
        bounded = node.value is not None and self._is_statically_bounded(node.value)
        for name in self._assigned_names(node.target):
            if bounded:
                self._bounded_names.add(name)
            else:
                self._bounded_names.discard(name)
        self.visit(node.target)
        self.visit(node.annotation)

    def _visit_loop(self, node: ast.AST) -> None:
        self.loops += 1
        bounded = False
        # Iterable expression is evaluated once, outside the loop body.
        if isinstance(node, (ast.For, ast.AsyncFor)):
            self.visit(node.iter)
            bounded = self._is_statically_bounded(node.iter)
            self.visit(node.target)
        if not bounded:
            self.unbounded_loops += 1
            self._loop_depth += 1
            self.max_loop_depth = max(self.max_loop_depth, self._loop_depth)
        for child in getattr(node, "body", ()):
            self.visit(child)
        if not bounded:
            self._loop_depth -= 1
        for child in getattr(node, "orelse", ()):
            self.visit(child)

    def visit_For(self, node: ast.For) -> None: self._visit_loop(node)
    def visit_AsyncFor(self, node: ast.AsyncFor) -> None: self._visit_loop(node)
    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        self._visit_loop(node)

    def visit_If(self, node: ast.If) -> None:
        self.branches += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.branches += 1
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self.branches += max(1, len(node.cases))
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self.branches += len(node.handlers)
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.branches += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def _visit_comprehension(
        self,
        node: ast.AST,
        generators: list[ast.comprehension],
        value_nodes: tuple[ast.AST, ...],
    ) -> None:
        """Model Python comprehension evaluation order precisely.

        Each generator iterable is evaluated *before* entering that generator's
        loop.  Therefore calls in ``for row in connection.execute(...)`` are
        one-shot setup work, while calls in later generator iterables execute
        once per preceding generator.  The previous generic traversal counted
        every iterable call at the deepest loop level and produced false
        database/I/O amplification findings.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: Traversal is linear in generator nodes, filter nodes, and value nodes; the nested source loops sum disjoint AST children rather than forming a Cartesian product.
        """

        self.comprehensions += 1
        previous = self._loop_depth
        try:
            for generator in generators:
                # Iterable expression is evaluated at the current depth.
                self.visit(generator.iter)
                self.loops += 1
                bounded = self._is_statically_bounded(generator.iter)
                if not bounded:
                    self.unbounded_loops += 1
                    self._loop_depth += 1
                    self.max_loop_depth = max(self.max_loop_depth, self._loop_depth)
                self.visit(generator.target)
                for condition in generator.ifs:
                    self.branches += 1
                    self.visit(condition)
            for value in value_nodes:
                self.visit(value)
        finally:
            self._loop_depth = previous

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node, node.generators, (node.elt,))

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node, node.generators, (node.elt,))

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node, node.generators, (node.key, node.value))

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node, node.generators, (node.elt,))

    def visit_Call(self, node: ast.Call) -> None:
        self.call_count += 1
        path = _call_path(node)
        components = set(path)
        leaf = path[-1] if path else ""
        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "add", "append", "clear", "discard", "extend", "insert", "pop",
            "popitem", "remove", "setdefault", "update",
        }:
            mutated = self._mutated_container_name(node.func.value)
            if mutated is not None:
                self._bounded_names.discard(mutated)
        if leaf in _SORT_COMPONENTS:
            self.sort_calls += 1
            bounded_sort = False
            if leaf == "sorted" and node.args:
                bounded_sort = self._is_statically_bounded(node.args[0])
            elif leaf in {"nsmallest", "nlargest"} and len(node.args) >= 2:
                bounded_sort = self._is_statically_bounded(node.args[1])
            elif leaf == "sort" and isinstance(node.func, ast.Attribute):
                bounded_sort = self._is_statically_bounded(node.func.value)
            if not bounded_sort:
                self.unbounded_sort_calls += 1
        recursive = False
        if isinstance(node.func, ast.Name):
            recursive = node.func.id == self.symbol_name
        elif isinstance(node.func, ast.Attribute):
            recursive = (
                node.func.attr == self.symbol_name
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"self", "cls"}
            )
        if recursive:
            self.recursive_calls += 1
        if self._loop_depth:
            if components & _DB_COMPONENTS and ("sqlite3" in components or leaf in _DB_COMPONENTS):
                self.database_calls_in_loops += 1
            if components & _SUBPROCESS_COMPONENTS and ("subprocess" in components or "os" in components):
                self.subprocess_calls_in_loops += 1
            if leaf in _LOCK_COMPONENTS:
                self.lock_calls_in_loops += 1
            if leaf in _SERIALIZATION_COMPONENTS:
                self.serialization_calls_in_loops += 1
            # Keep I/O narrow to explicit filesystem/network APIs; generic str.replace etc. are excluded.
            if leaf in _IO_COMPONENTS or (components & {"pathlib", "socket", "requests", "urllib"}):
                self.io_calls_in_loops += 1
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Nested function bodies are independent symbols and must not inflate parent metrics.
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


class PythonAlgorithmAnalyzer:
    language = AlgorithmLanguage.PYTHON
    revision = "python-ast-v5"

    def __init__(self, source_index: RepositorySourceIndexPort | None = None) -> None:
        self._source_index = source_index

    def analyze(self, document: SourceDocument) -> FileAnalysis:
        if self._source_index is None:
            try:
                tree = ast.parse(document.text, filename=document.relative_path)
            except SyntaxError:
                return FileAnalysis(document.relative_path, document.language, document.sha256, self.revision, (), 1)
        else:
            tree = self._source_index.python_tree(document.relative_path, sha256=document.sha256)

        symbols: list[AlgorithmSymbol] = []

        def walk_body(body: list[ast.stmt], prefix: tuple[str, ...]) -> None:
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified = ".".join((*prefix, node.name))
                    visitor = _FunctionMetricsVisitor(node.name)
                    for stmt in node.body:
                        visitor.visit(stmt)
                    line_end = int(getattr(node, "end_lineno", node.lineno))
                    declared_complexity, complexity_rationale = _complexity_contract(node)
                    base = AlgorithmMetrics(
                        source_lines=max(1, line_end - node.lineno + 1),
                        branches=visitor.branches,
                        loops=visitor.loops,
                        max_loop_depth=visitor.max_loop_depth,
                        comprehensions=visitor.comprehensions,
                        sort_calls=visitor.sort_calls,
                        database_calls_in_loops=visitor.database_calls_in_loops,
                        io_calls_in_loops=visitor.io_calls_in_loops,
                        serialization_calls_in_loops=visitor.serialization_calls_in_loops,
                        lock_calls_in_loops=visitor.lock_calls_in_loops,
                        subprocess_calls_in_loops=visitor.subprocess_calls_in_loops,
                        recursive_calls=visitor.recursive_calls,
                        call_count=visitor.call_count,
                        cyclomatic_estimate=1 + visitor.branches + visitor.loops,
                        estimated_complexity=(
                            declared_complexity
                            or estimated_complexity(
                                loops=visitor.unbounded_loops,
                                max_loop_depth=visitor.max_loop_depth,
                                sort_calls=visitor.unbounded_sort_calls,
                                recursive_calls=visitor.recursive_calls,
                            )
                        ),
                    )
                    score, findings = score_metrics(
                        base,
                        declared_complexity=declared_complexity,
                        rationale=complexity_rationale,
                    )
                    metrics = replace(base, risk_score=score)
                    symbols.append(AlgorithmSymbol(
                        symbol_id=f"{document.relative_path}::{qualified}",
                        relative_path=document.relative_path,
                        language=document.language,
                        qualified_name=qualified,
                        line_start=node.lineno,
                        line_end=line_end,
                        metrics=metrics,
                        findings=findings,
                    ))
                    walk_body(node.body, (*prefix, node.name))
                elif isinstance(node, ast.ClassDef):
                    walk_body(node.body, (*prefix, node.name))

        walk_body(tree.body, ())
        return FileAnalysis(document.relative_path, document.language, document.sha256, self.revision, tuple(symbols), 0)


__all__ = ["PythonAlgorithmAnalyzer"]
