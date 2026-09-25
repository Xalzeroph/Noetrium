from __future__ import annotations

from noetrium_platform.composition.diagnostic_io import open_diagnostic_evidence, verify_crash_bundle_artifact
from noetrium_platform.composition.runtime_status import build_runtime_status_service
from noetrium_platform.composition.runtime_status_config import load_runtime_status_layout
from noetrium_platform.composition.concurrency import build_execution_concurrency_runtime

from .failure_catalog import FailureCatalogView
from .recovery_inspect import read_recovery_state
from .runtime_recovery_plan import render_runtime_recovery_plan


def route_runtime(args: object):
    command = getattr(args, "command", None)
    if command in {"runtime-status", "runtime-recovery-plan"}:
        layout = load_runtime_status_layout(args.layout)
        concurrency_runtime = build_execution_concurrency_runtime()
        task_group = concurrency_runtime.open_task_group("operator-runtime-status")
        try:
            with open_diagnostic_evidence(layout.forensic_root) as evidence:
                status = build_runtime_status_service(
                    layout,
                    evidence,
                    task_group=task_group,
                ).snapshot()
                return status.to_dict() if command == "runtime-status" else render_runtime_recovery_plan(status)
        finally:
            concurrency_runtime.close()
    if command == "failure-catalog":
        return FailureCatalogView().query(domain=args.domain, code=args.code)
    if command == "crash-bundle-verify":
        return verify_crash_bundle_artifact(args.path)
    if command == "recovery-state":
        return read_recovery_state(args.path)
    return None


__all__ = ["route_runtime"]
