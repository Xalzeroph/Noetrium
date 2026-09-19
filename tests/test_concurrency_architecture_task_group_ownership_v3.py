from __future__ import annotations

import ast
from pathlib import Path


RUNTIME = Path(__file__).parents[1] / "noetrium_platform/foundation/kernel/concurrency/runtime"


def _class_assignments(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    init = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    return {
        node.attr
        for node in ast.walk(init)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and isinstance(node.ctx, ast.Store)
    }


def test_task_group_delegates_mutable_child_and_close_authority() -> None:
    fields = _class_assignments(RUNTIME / "task_group.py", "StructuredTaskGroup")
    assert {"_state", "_lifecycle"} <= fields
    assert not fields.intersection(
        {"_tasks", "_recurring", "_scheduled_handles", "_active_submissions", "_close_failure", "_closed"}
    )


def test_task_state_authority_owns_child_records_and_lock() -> None:
    fields = _class_assignments(RUNTIME / "task_state.py", "_TaskStateAuthority")
    assert {"_tasks", "_recurring", "_lock"} <= fields


def test_task_group_lifecycle_authority_owns_close_and_submission_state() -> None:
    fields = _class_assignments(RUNTIME / "task_lifecycle.py", "_TaskGroupLifecycleAuthority")
    assert {
        "_condition",
        "_active_submissions",
        "_closing",
        "_closed",
        "_converged",
        "_close_complete",
        "_close_failure",
        "_group_deadline_handle",
    } <= fields


def test_scheduled_handle_does_not_compete_for_timer_cancellation_authority() -> None:
    source = (RUNTIME / "task_handles.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_OwnedScheduledHandle")
    cancel = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "cancel")
    calls = {ast.unparse(node.func) for node in ast.walk(cancel) if isinstance(node, ast.Call)}
    assert "self._group._cancel_recurring" in calls
    assert "self._timer_handle.cancel" not in calls
