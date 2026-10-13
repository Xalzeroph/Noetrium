from __future__ import annotations

from pathlib import Path

from .source_scan import SourceInvariantViolation, imports, violation


_OLD_START_WAL = (
    "start_intent_store.py",
    "start_intent_index.py",
    "start_intent_ports.py",
    "start_journal.py",
)


def audit_runtime_service_start_invariants(
    root: Path,
) -> list[SourceInvariantViolation]:
    service_runtime = (
        root
        / "noetrium_platform"
        / "infrastructure"
        / "lifecycle"
        / "service"
        / "runtime"
    )
    rows: list[SourceInvariantViolation] = []
    for name in _OLD_START_WAL:
        path = service_runtime / name
        if path.exists():
            rows.append(
                violation(
                    root,
                    path,
                    "service_start_single_effect_journal",
                    1,
                    "legacy service-specific start WAL is forbidden; use ServiceStartEffectJournal over EffectIntentJournal",
                )
            )

    for name in (
        "start_coordination.py",
        "start_new_flow.py",
        "start_recovery_flow.py",
        "service_quiescence_control.py",
        "service_observation.py",
        "supervisor.py",
    ):
        path = service_runtime / name
        if not path.exists():
            continue
        modules = tuple(module for module, _line in imports(path))
        if any(
            module.endswith((
                "start_intent_store",
                "start_intent_index",
                "start_intent_ports",
                "start_journal",
            ))
            for module in modules
        ):
            rows.append(
                violation(
                    root,
                    path,
                    "service_start_single_effect_journal",
                    1,
                    "service start flow reintroduced a private durable WAL",
                )
            )
    return rows


__all__ = ["audit_runtime_service_start_invariants"]
