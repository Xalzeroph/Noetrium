from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, violation


def audit_service_supervisor_invariants(root: Path) -> list[SourceInvariantViolation]:
    service_os = root / "noetrium_platform" / "infrastructure" / "lifecycle" / "service" / "runtime"
    rows: list[SourceInvariantViolation] = []

    supervisor = service_os / "supervisor.py"
    if supervisor.exists():
        tree = source_tree(supervisor)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and target.attr in {"store", "adapter", "start_journal"}
                    ):
                        rows.append(
                            violation(
                                root,
                                supervisor,
                                "service_supervisor_encapsulation",
                                node.lineno,
                                f"ExactServiceSupervisor exposes mutable runtime dependency self.{target.attr}; keep dependencies inside narrow coordinators",
                            )
                        )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "write":
                rows.append(
                    violation(
                        root,
                        supervisor,
                        "service_state_single_writer",
                        node.lineno,
                        "service supervisor façade writes state directly; route every state publication through ServiceStateTransitionWriter",
                    )
                )

    # Supervisor-state publication has exactly one source authority. Durable
    # journals/capture files are separate domains and are not covered here.
    for path in service_os.glob("*.py"):
        if path.name in {"state_transition.py", "state_storage.py"}:
            continue
        tree = source_tree(path)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "write"):
                continue
            value = node.func.value
            if isinstance(value, ast.Attribute) and value.attr in {"_store", "store"}:
                rows.append(
                    violation(
                        root,
                        path,
                        "service_state_single_writer",
                        node.lineno,
                        "service runtime writes supervisor state outside ServiceStateTransitionWriter",
                    )
                )
    return rows


__all__ = ["audit_service_supervisor_invariants"]
