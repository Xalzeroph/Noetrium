from __future__ import annotations

import ast

ALLOWED_THREAD_PREFIXES = (
    "noetrium_platform/foundation/kernel/concurrency/providers/",
    "noetrium_platform/foundation/kernel/kernel/process/",
)
ALLOWED_EXECUTOR_PREFIXES = (
    "noetrium_platform/foundation/kernel/concurrency/providers/",
)
ALLOWED_TASK_PREFIXES = (
    "noetrium_platform/foundation/kernel/concurrency/providers/",
)
BLOCKING_ASYNC_EXACT = {
    "time.sleep",
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "os.system",
}
BLOCKING_ASYNC_LEAVES = {
    "read_bytes", "read_text", "write_bytes", "write_text", "open", "execute",
    "executemany", "wait",
}
SLOW_UNDER_LOCK = {
    "open", "read_bytes", "read_text", "write_bytes", "write_text", "execute",
    "executemany", "executescript", "connect", "send", "recv", "request", "urlopen",
    "run", "Popen", "wait", "join", "sleep", "fsync",
}
SLOW_EXACT = {
    "os.open", "os.close", "os.read", "os.write", "os.pread", "os.pwrite",
    "os.fsync", "os.fdatasync", "os.stat", "os.fstat", "os.replace", "os.rename",
}
LOCK_NAMES = {"Lock", "RLock", "Condition", "Semaphore", "BoundedSemaphore"}
QUEUE_NAMES = {"Queue", "LifoQueue", "PriorityQueue"}
THREAD_NAMES = {"Thread"}
THREAD_POOL_NAMES = {"ThreadPoolExecutor"}
PROCESS_POOL_NAMES = {"ProcessPoolExecutor"}
TASK_NAMES = {"create_task", "ensure_future"}
SUBPROCESS_NAMES = {"Popen", "run", "call", "check_call", "check_output"}

OWNED_WAIT_POLICY = "OWNED_CONDITION_WAIT"
BOUNDED_FANOUT_POLICY = "BOUNDED_TASK_FANOUT"
CONCURRENCY_POLICIES = {OWNED_WAIT_POLICY, BOUNDED_FANOUT_POLICY}


def concurrency_contract(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str | None, str | None]:
    doc = ast.get_docstring(node, clean=False) or ""
    policy = None
    rationale = None
    for raw_line in doc.splitlines():
        line = raw_line.strip()
        if line.startswith("Concurrency-Policy:"):
            candidate = line.split(":", 1)[1].strip()
            if candidate in CONCURRENCY_POLICIES:
                policy = candidate
        elif line.startswith("Concurrency-Rationale:"):
            candidate = line.split(":", 1)[1].strip()
            if len(candidate) >= 20:
                rationale = candidate
    if policy is None or rationale is None:
        return None, None
    return policy, rationale


def call_name(node: ast.Call) -> str:
    value = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def call_leaf(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def queue_is_bounded(node: ast.Call) -> bool:
    if node.args:
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, int):
            return first.value > 0
        return True
    for keyword in node.keywords:
        if keyword.arg == "maxsize":
            if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, int):
                return keyword.value.value > 0
            return True
    return False


def has_timeout(node: ast.Call) -> bool:
    if node.args:
        return True
    return any(k.arg in {"timeout", "timeout_seconds"} for k in node.keywords)


def is_literal_join(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Constant)
        and isinstance(node.func.value.value, (str, bytes))
        and node.func.attr == "join"
    )


def is_lifecycle_join(node: ast.Call, name: str) -> bool:
    return call_leaf(name) == "join" and not is_literal_join(node)


def is_slow_call(node: ast.Call, name: str) -> bool:
    leaf = call_leaf(name)
    lifecycle_join = is_lifecycle_join(node, name)
    return name in SLOW_EXACT or (
        leaf in SLOW_UNDER_LOCK and (leaf != "join" or lifecycle_join)
    )

def is_blocking_async_call(
    node: ast.Call,
    name: str,
    *,
    awaited_wait: bool,
) -> bool:
    leaf = call_leaf(name)
    return (
        name in BLOCKING_ASYNC_EXACT
        or (leaf in BLOCKING_ASYNC_LEAVES and not awaited_wait)
        or is_lifecycle_join(node, name)
    )


__all__ = [
    "ALLOWED_EXECUTOR_PREFIXES", "ALLOWED_TASK_PREFIXES", "ALLOWED_THREAD_PREFIXES",
    "BOUNDED_FANOUT_POLICY", "LOCK_NAMES", "OWNED_WAIT_POLICY", "PROCESS_POOL_NAMES",
    "QUEUE_NAMES", "SUBPROCESS_NAMES", "TASK_NAMES", "THREAD_NAMES", "THREAD_POOL_NAMES",
    "call_leaf", "call_name", "concurrency_contract", "has_timeout", "is_blocking_async_call",
    "is_lifecycle_join", "is_slow_call", "queue_is_bounded",
]