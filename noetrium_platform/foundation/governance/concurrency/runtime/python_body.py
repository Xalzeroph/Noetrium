from __future__ import annotations

import ast

from noetrium_platform.foundation.governance.concurrency.api import (
    ConcurrencyFinding,
    ConcurrencyMetrics,
    ConcurrencyPriority,
)

from .python_call_graph import LocalBlockingCatalog
from .python_rules import (
    ALLOWED_EXECUTOR_PREFIXES,
    ALLOWED_TASK_PREFIXES,
    ALLOWED_THREAD_PREFIXES,
    BOUNDED_FANOUT_POLICY,
    LOCK_NAMES,
    OWNED_WAIT_POLICY,
    PROCESS_POOL_NAMES,
    QUEUE_NAMES,
    SUBPROCESS_NAMES,
    TASK_NAMES,
    THREAD_NAMES,
    THREAD_POOL_NAMES,
    call_leaf,
    call_name,
    has_timeout,
    is_blocking_async_call,
    is_lifecycle_join,
    is_slow_call,
    queue_is_bounded,
)

class BodyAnalyzer(ast.NodeVisitor):
    def __init__(
        self,
        *,
        relative_path: str,
        qualified_name: str,
        async_function: bool,
        concurrency_policy: str | None,
        local_blocking: LocalBlockingCatalog,
    ) -> None:
        self.relative_path = relative_path
        self.qualified_name = qualified_name
        self.async_function = async_function
        self.concurrency_policy = concurrency_policy
        self.local_blocking = local_blocking
        self.loop_depth = 0
        self.lock_depth = 0
        self.await_depth = 0
        self.values = {name: 0 for name in ConcurrencyMetrics.__dataclass_fields__}
        self.values["async_functions"] = int(async_function)
        self.findings: list[ConcurrencyFinding] = []

    def _add(self, priority: ConcurrencyPriority, code: str, detail: str, line: int) -> None:
        self.findings.append(ConcurrencyFinding(priority, code, detail, line))

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.target)
        self.visit(node.iter)
        self.loop_depth += 1
        for stmt in node.body:
            self.visit(stmt)
        self.loop_depth -= 1
        for stmt in node.orelse:
            self.visit(stmt)

    visit_AsyncFor = visit_For

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        self.loop_depth += 1
        for stmt in node.body:
            self.visit(stmt)
        self.loop_depth -= 1
        for stmt in node.orelse:
            self.visit(stmt)

    def visit_With(self, node: ast.With) -> None:
        lock_scope = any(self._looks_lock_context(item.context_expr) for item in node.items)
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars:
                self.visit(item.optional_vars)
        if lock_scope:
            self.values["lock_scopes"] += 1
            self.lock_depth += 1
        for stmt in node.body:
            self.visit(stmt)
        if lock_scope:
            self.lock_depth -= 1

    visit_AsyncWith = visit_With
    @staticmethod
    def _looks_lock_context(node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return "lock" in node.id.lower() or "condition" in node.id.lower()
        if isinstance(node, ast.Attribute):
            return "lock" in node.attr.lower() or "condition" in node.attr.lower()
        return False

    def visit_Await(self, node: ast.Await) -> None:
        self.values["await_calls"] += 1
        self.await_depth += 1
        try:
            self.visit(node.value)
        finally:
            self.await_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        name = call_name(node)
        leaf = call_leaf(name)
        line = getattr(node, "lineno", 0)
        if leaf in THREAD_NAMES:
            self.values["thread_constructors"] += 1
            daemon = any(
                k.arg == "daemon" and isinstance(k.value, ast.Constant) and bool(k.value.value)
                for k in node.keywords
            )
            if daemon:
                self.values["daemon_threads"] += 1
                if not self.relative_path.startswith(ALLOWED_THREAD_PREFIXES):
                    self._add(
                        ConcurrencyPriority.P1,
                        "daemon-thread-lifecycle",
                        "daemon thread is not owned by the platform concurrency provider",
                        line,
                    )
            if not self.relative_path.startswith(ALLOWED_THREAD_PREFIXES):
                self._add(
                    ConcurrencyPriority.P1,
                    "unmanaged-thread",
                    "thread construction bypasses platform.concurrency",
                    line,
                )
        if leaf in THREAD_POOL_NAMES:
            self.values["thread_pool_constructors"] += 1
            if not self.relative_path.startswith(ALLOWED_EXECUTOR_PREFIXES):
                self._add(
                    ConcurrencyPriority.P1,
                    "unmanaged-thread-pool",
                    "ThreadPoolExecutor bypasses platform.concurrency",
                    line,
                )
        if leaf in PROCESS_POOL_NAMES:
            self.values["process_pool_constructors"] += 1
            if not self.relative_path.startswith(ALLOWED_EXECUTOR_PREFIXES):
                self._add(
                    ConcurrencyPriority.P1,
                    "unmanaged-process-pool",
                    "ProcessPoolExecutor bypasses platform.concurrency",
                    line,
                )
        if leaf in TASK_NAMES:
            self.values["task_creations"] += 1
            if self.loop_depth:
                self.values["fanout_in_loops"] += 1
                self._add(
                    ConcurrencyPriority.P1,
                    "unbounded-task-fanout",
                    "async task creation occurs inside a loop without visible admission bound",
                    line,
                )
            if not self.relative_path.startswith(ALLOWED_TASK_PREFIXES):
                self._add(
                    ConcurrencyPriority.P1,
                    "unmanaged-async-task",
                    "async task creation bypasses structured concurrency ownership",
                    line,
                )
        if leaf in QUEUE_NAMES:
            self.values["queue_constructors"] += 1
            if not queue_is_bounded(node):
                self.values["unbounded_queues"] += 1
                self._add(
                    ConcurrencyPriority.P0,
                    "unbounded-queue",
                    "queue has no explicit positive capacity/backpressure",
                    line,
                )
        if leaf in LOCK_NAMES:
            self.values["lock_constructors"] += 1
        if leaf in SUBPROCESS_NAMES and (name.startswith("subprocess.") or leaf == "Popen"):
            self.values["subprocess_constructors"] += 1

        lifecycle_join = is_lifecycle_join(node, name)
        if lifecycle_join:
            self.values["lifecycle_join_calls"] += 1
        awaited_wait = leaf == "wait" and self.await_depth > 0
        wait_like = (leaf in {"wait", "result"} or lifecycle_join) and not awaited_wait
        condition_wait = leaf == "wait" and "condition" in name.lower()
        if wait_like and not has_timeout(node):
            self.values["timeoutless_waits"] += 1
            owned_receive = condition_wait and self.concurrency_policy == OWNED_WAIT_POLICY
            if not owned_receive:
                self._add(
                    ConcurrencyPriority.P2,
                    "timeoutless-wait",
                    "blocking wait has no explicit deadline/timeout",
                    line,
                )
        if self.async_function and is_blocking_async_call(
            node,
            name,
            awaited_wait=awaited_wait,
        ):
            self.values["blocking_calls_in_async"] += 1
            self._add(
                ConcurrencyPriority.P0,
                "blocking-in-async",
                f"blocking call in async function: {name or leaf}",
                line,
            )

        slow_leaf = is_slow_call(node, name)
        indirect_slow = self.local_blocking.is_blocking_helper(self.qualified_name, name)
        if self.lock_depth and (slow_leaf or indirect_slow) and not condition_wait:
            self.values["blocking_calls_under_lock"] += 1
            helper_only = indirect_slow and not slow_leaf
            code = "blocking-helper-under-lock" if helper_only else "blocking-under-lock"
            detail = (
                f"call while lock is held reaches a local helper with blocking I/O: {name or leaf}"
                if helper_only
                else f"potentially slow/blocking call while lock is held: {name or leaf}"
            )
            self._add(ConcurrencyPriority.P1, code, detail, line)
        if self.loop_depth and leaf in {"submit", "map"}:
            self.values["fanout_in_loops"] += 1
            if self.concurrency_policy != BOUNDED_FANOUT_POLICY:
                self._add(
                    ConcurrencyPriority.P2,
                    "executor-fanout-in-loop",
                    "executor fanout occurs in a loop without a reviewed bounded-fanout contract",
                    line,
                )
        self.generic_visit(node)

    def metrics(self) -> ConcurrencyMetrics:
        return ConcurrencyMetrics(**self.values)


__all__ = ["BodyAnalyzer"]