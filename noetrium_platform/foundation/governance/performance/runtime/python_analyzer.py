from __future__ import annotations

import ast
import hashlib

from noetrium_platform.foundation.governance.api import RepositorySourceIndexPort
from noetrium_platform.foundation.governance.performance.api import (
    PerformanceDocument, PerformanceFileAnalysis, PerformanceFinding, PerformanceHotspot,
    PerformanceLanguage, PerformanceMetrics, PerformancePriority,
)


def _call_name(node: ast.Call) -> str:
    value = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr); value = value.value
    if isinstance(value, ast.Name): parts.append(value.id)
    return ".".join(reversed(parts))


def _is_component(name: str, components: set[str]) -> bool:
    parts = set(name.split("."))
    return bool(parts & components)


def _looks_database_call(name: str) -> bool:
    parts = name.split(".")
    leaf = parts[-1] if parts else ""
    lowered = tuple(part.lower().lstrip("_") for part in parts[:-1])
    if name == "sqlite3.connect":
        return True
    if leaf not in {"execute", "executemany", "executescript", "cursor"}:
        return False
    database_markers = ("conn", "connection", "cursor", "sqlite", "database", "db")
    return any(any(marker in part for marker in database_markers) for part in lowered)


_DB = {"execute", "executemany", "executescript", "connect", "cursor"}
_IO = {"open", "read", "write", "read_bytes", "read_text", "write_bytes", "write_text", "send", "recv", "request", "urlopen"}
_SERIAL = {"dumps", "dump", "loads", "load", "encode", "decode", "canonical_bytes", "canonical_digest"}
_LOCK = {"acquire", "release", "Lock", "RLock", "Semaphore", "Condition"}
_SYNC_SUBPROCESS = {"subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_call", "subprocess.check_output", "os.system"}
_BLOCKING_ASYNC = _SYNC_SUBPROCESS | {"time.sleep", "Path.read_bytes", "Path.read_text", "Path.write_bytes", "Path.write_text"}


class _FunctionAnalyzer(ast.NodeVisitor):
    def __init__(self, *, qualified_name: str, async_function: bool) -> None:
        self.qualified_name = qualified_name
        self.async_function = async_function
        self.loop_depth = 0
        self.max_loop_depth = 0
        self.bounded_fanout_depth = 0
        self.values = {field: 0 for field in PerformanceMetrics.__dataclass_fields__ if field != "risk_score"}
        self.values["async_functions"] = int(async_function)

    def visit_For(self, node: ast.For) -> None:
        # ``iter`` is evaluated once before the loop.  Counting calls there as
        # body amplification would misclassify streaming idioms such as
        # ``for chunk in iter(lambda: fh.read(n), b"")``.
        self.visit(node.target)
        self.visit(node.iter)
        self.loop_depth += 1; self.max_loop_depth = max(self.max_loop_depth, self.loop_depth)
        for stmt in node.body: self.visit(stmt)
        self.loop_depth -= 1
        for stmt in node.orelse: self.visit(stmt)

    visit_AsyncFor = visit_For

    @staticmethod
    def _has_explicit_fanout_bound(test: ast.AST) -> bool:
        """Recognize a rolling-window guard such as ``len(active) < workers``.

        This is deliberately narrow: only a positive comparison around ``len``
        proves that submissions inside the guarded loop cannot accumulate an
        unbounded active set.  Provider-level backpressure alone is not used as
        static proof because it is invisible at the call site.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: The AST test expression is walked once and each comparison checks a constant two operand orientations; no candidate scan multiplies the AST traversal.
        """

        for node in ast.walk(test):
            if not isinstance(node, ast.Compare) or len(node.ops) != 1:
                continue
            left, op, right = node.left, node.ops[0], node.comparators[0]
            candidates = ((left, op, right), (right, op, left))
            for maybe_len, comparator, bound in candidates:
                if not (
                    isinstance(maybe_len, ast.Call)
                    and isinstance(maybe_len.func, ast.Name)
                    and maybe_len.func.id == "len"
                    and len(maybe_len.args) == 1
                ):
                    continue
                if isinstance(comparator, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)) and not (
                    isinstance(bound, ast.Constant) and bound.value in {0, None}
                ):
                    return True
        return False

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        self.loop_depth += 1; self.max_loop_depth = max(self.max_loop_depth, self.loop_depth)
        bounded = self._has_explicit_fanout_bound(node.test)
        if bounded:
            self.bounded_fanout_depth += 1
        for stmt in node.body: self.visit(stmt)
        if bounded:
            self.bounded_fanout_depth -= 1
        self.loop_depth -= 1
        for stmt in node.orelse: self.visit(stmt)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        if self.loop_depth: self.values["loop_allocations"] += 1
        self.generic_visit(node)

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp

    def visit_Await(self, node: ast.Await) -> None:
        self.values["await_calls"] += 1; self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        parts = name.split(".")
        leaf = parts[-1] if parts else ""
        if _looks_database_call(name):
            self.values["database_calls"] += 1
            if self.loop_depth: self.values["database_calls_in_loops"] += 1
        if leaf in _IO or name in {"Path.read_bytes", "Path.read_text", "Path.write_bytes", "Path.write_text"}:
            self.values["io_calls"] += 1
            if self.loop_depth: self.values["io_calls_in_loops"] += 1
        if leaf in {"read_bytes", "read_text"}: self.values["whole_file_reads"] += 1
        if leaf in {"write_bytes", "write_text"}: self.values["whole_file_writes"] += 1
        if leaf in _SERIAL:
            self.values["serialization_calls"] += 1
            if self.loop_depth: self.values["serialization_calls_in_loops"] += 1
        if leaf in _LOCK:
            self.values["lock_calls"] += 1
            if self.loop_depth: self.values["lock_calls_in_loops"] += 1
        if leaf == "ThreadPoolExecutor": self.values["thread_pool_constructors"] += 1
        if leaf == "ProcessPoolExecutor": self.values["process_pool_constructors"] += 1
        if leaf in {"create_task", "ensure_future", "submit"}: self.values["task_creations"] += 1
        if leaf in {"gather", "wait"}: self.values["gather_calls"] += 1
        if leaf in {"Queue", "LifoQueue", "PriorityQueue"}:
            bounded = bool(node.args) or any(k.arg in {"maxsize"} and not (isinstance(k.value, ast.Constant) and k.value.value == 0) for k in node.keywords)
            if not bounded: self.values["unbounded_queue_constructors"] += 1
        if leaf == "list": self.values["list_materializations"] += 1
        if leaf in {"deepcopy", "copytree"}: self.values["deep_copy_calls"] += 1
        if self.loop_depth and leaf in {"list", "dict", "set", "bytearray", "BytesIO", "StringIO"}: self.values["loop_allocations"] += 1
        if self.async_function:
            if name == "time.sleep": self.values["sleep_calls_in_async"] += 1
            if name in _SYNC_SUBPROCESS: self.values["sync_subprocess_calls_in_async"] += 1
            if name in _BLOCKING_ASYNC or leaf in {"read_bytes", "read_text", "write_bytes", "write_text"}:
                self.values["blocking_calls_in_async"] += 1
        # Obvious eager fanout: gather(*(call(x) for x in ...)) or submit/create_task inside a loop.
        if leaf in {"gather", "wait"} and any(isinstance(arg, ast.Starred) and isinstance(arg.value, (ast.GeneratorExp, ast.ListComp)) for arg in node.args):
            self.values["unbounded_fanout_calls"] += 1
        if (
            self.loop_depth
            and not self.bounded_fanout_depth
            and leaf in {"create_task", "ensure_future", "submit"}
        ):
            self.values["unbounded_fanout_calls"] += 1
        self.generic_visit(node)

    def metrics(self) -> PerformanceMetrics:
        self.values["max_loop_depth"] = self.max_loop_depth
        score = 0
        score += self.values["blocking_calls_in_async"] * 20
        score += self.values["sync_subprocess_calls_in_async"] * 25
        score += self.values["sleep_calls_in_async"] * 25
        score += self.values["database_calls_in_loops"] * 15
        score += self.values["io_calls_in_loops"] * 10
        score += self.values["serialization_calls_in_loops"] * 7
        score += self.values["lock_calls_in_loops"] * 12
        score += self.values["unbounded_fanout_calls"] * 18
        score += self.values["unbounded_queue_constructors"] * 15
        score += self.values["whole_file_reads"] * 3 + self.values["whole_file_writes"] * 2
        score += self.values["deep_copy_calls"] * 5 + self.values["loop_allocations"] * 3
        self.values["risk_score"] = min(100, score)
        return PerformanceMetrics(**self.values)


def _findings(m: PerformanceMetrics) -> tuple[PerformanceFinding, ...]:
    rows: list[PerformanceFinding] = []
    def add(priority, code, detail): rows.append(PerformanceFinding(priority, code, detail, m.risk_score))
    if m.sleep_calls_in_async: add(PerformancePriority.P0, "blocking-sleep-in-async", "time.sleep blocks an async event loop")
    if m.sync_subprocess_calls_in_async: add(PerformancePriority.P0, "sync-subprocess-in-async", "synchronous subprocess call blocks an async event loop")
    if m.blocking_calls_in_async and not (m.sleep_calls_in_async or m.sync_subprocess_calls_in_async): add(PerformancePriority.P1, "blocking-io-in-async", "blocking filesystem/I/O call appears in async code")
    if m.database_calls_in_loops: add(PerformancePriority.P1, "database-roundtrip-in-loop", "database operations are amplified by loop cardinality")
    if m.unbounded_fanout_calls: add(PerformancePriority.P1, "unbounded-fanout", "task/future fanout has no explicit concurrency bound")
    if m.unbounded_queue_constructors: add(PerformancePriority.P1, "unbounded-queue", "queue has no explicit backpressure capacity")
    if m.lock_calls_in_loops: add(PerformancePriority.P2, "lock-in-loop", "repeated lock acquisition may amplify contention")
    if m.io_calls_in_loops: add(PerformancePriority.P2, "io-in-loop", "I/O is amplified by loop cardinality")
    if m.serialization_calls_in_loops: add(PerformancePriority.P2, "serialization-in-loop", "serialization is amplified by loop cardinality")
    if m.whole_file_reads >= 2: add(PerformancePriority.P2, "whole-file-read", "multiple whole-file reads may cause avoidable peak memory")
    if m.deep_copy_calls: add(PerformancePriority.P2, "deep-copy", "deep copy may duplicate large object graphs")
    if m.loop_allocations >= 2: add(PerformancePriority.P3, "allocation-in-loop", "loop repeatedly allocates materialized containers")
    return tuple(rows)


class PythonPerformanceAnalyzer:
    language = PerformanceLanguage.PYTHON
    revision = "python-performance-ast-v4"

    def __init__(self, source_index: RepositorySourceIndexPort | None = None) -> None:
        self._source_index = source_index

    def analyze(self, document: PerformanceDocument) -> PerformanceFileAnalysis:
        if self._source_index is None:
            try:
                tree = ast.parse(document.text, filename=document.relative_path)
            except SyntaxError:
                return PerformanceFileAnalysis(document.relative_path, document.language, document.sha256, self.revision, (), 1)
        else:
            tree = self._source_index.python_tree(document.relative_path, sha256=document.sha256)
        hotspots: list[PerformanceHotspot] = []
        stack: list[str] = []

        def walk_body(body, prefix: tuple[str, ...] = ()):
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    q = ".".join((*prefix, node.name))
                    analyzer = _FunctionAnalyzer(qualified_name=q, async_function=isinstance(node, ast.AsyncFunctionDef))
                    # Do not include nested function bodies in parent metrics.
                    for stmt in node.body:
                        if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            analyzer.visit(stmt)
                    metrics = analyzer.metrics(); findings = _findings(metrics)
                    if findings:
                        hotspots.append(PerformanceHotspot(
                            hotspot_id=f"{document.relative_path}::{q}", relative_path=document.relative_path,
                            language=document.language, qualified_name=q, line_start=node.lineno,
                            line_end=getattr(node, "end_lineno", node.lineno), metrics=metrics, findings=findings,
                        ))
                    walk_body(node.body, (*prefix, node.name))
                elif isinstance(node, ast.ClassDef):
                    walk_body(node.body, (*prefix, node.name))
        walk_body(tree.body)
        return PerformanceFileAnalysis(document.relative_path, document.language, document.sha256, self.revision, tuple(hotspots), 0)
