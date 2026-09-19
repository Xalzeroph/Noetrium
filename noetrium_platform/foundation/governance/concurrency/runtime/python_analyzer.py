from __future__ import annotations

import ast

from noetrium_platform.foundation.governance.api import RepositorySourceIndexPort
from noetrium_platform.foundation.governance.concurrency.api import (
    ConcurrencyDocument,
    ConcurrencyFileAnalysis,
    ConcurrencyHotspot,
    ConcurrencyLanguage,
    ConcurrencyMetrics,
)

from .python_body import BodyAnalyzer
from .python_call_graph import LocalBlockingCatalog
from .python_rules import concurrency_contract


class PythonConcurrencyAnalyzer:
    language = ConcurrencyLanguage.PYTHON
    revision = "python-concurrency-ast-v10"

    def __init__(self, source_index: RepositorySourceIndexPort | None = None) -> None:
        self._source_index = source_index

    def analyze(self, document: ConcurrencyDocument) -> ConcurrencyFileAnalysis:
        if self._source_index is None:
            try:
                tree = ast.parse(document.text, filename=document.relative_path)
            except SyntaxError:
                return ConcurrencyFileAnalysis(
                    document.relative_path,
                    document.language,
                    document.sha256,
                    self.revision,
                    (),
                    1,
                )
        else:
            tree = self._source_index.python_tree(document.relative_path, sha256=document.sha256)

        hotspots: list[ConcurrencyHotspot] = []
        local_blocking = LocalBlockingCatalog(tree)

        def walk(body: list[ast.stmt], prefix: tuple[str, ...] = ()) -> None:
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified = ".".join((*prefix, node.name))
                    concurrency_policy, _rationale = concurrency_contract(node)
                    analyzer = BodyAnalyzer(
                        relative_path=document.relative_path,
                        qualified_name=qualified,
                        async_function=isinstance(node, ast.AsyncFunctionDef),
                        concurrency_policy=concurrency_policy,
                        local_blocking=local_blocking,
                    )
                    for stmt in node.body:
                        if not isinstance(
                            stmt,
                            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                        ):
                            analyzer.visit(stmt)
                    metrics = analyzer.metrics()
                    findings = tuple(analyzer.findings)
                    has_primitives = any(
                        getattr(metrics, field)
                        for field in ConcurrencyMetrics.__dataclass_fields__
                    )
                    if findings or has_primitives:
                        hotspots.append(
                            ConcurrencyHotspot(
                                hotspot_id=f"{document.relative_path}::{qualified}",
                                relative_path=document.relative_path,
                                language=document.language,
                                qualified_name=qualified,
                                line_start=node.lineno,
                                line_end=getattr(node, "end_lineno", node.lineno),
                                metrics=metrics,
                                findings=findings,
                            )
                        )
                    walk(node.body, (*prefix, node.name))
                elif isinstance(node, ast.ClassDef):
                    walk(node.body, (*prefix, node.name))

        walk(tree.body)
        return ConcurrencyFileAnalysis(
            document.relative_path,
            document.language,
            document.sha256,
            self.revision,
            tuple(hotspots),
            0,
        )


__all__ = ["PythonConcurrencyAnalyzer"]