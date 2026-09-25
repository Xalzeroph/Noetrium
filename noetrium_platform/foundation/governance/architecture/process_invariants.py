from __future__ import annotations

from pathlib import Path

from .source_scan import SourceInvariantViolation, imports, violation


def audit_process_invariants(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    process_api = root / "noetrium_platform" / "infrastructure" / "lifecycle" / "process" / "api"
    if process_api.exists():
        for path in sorted(process_api.rglob("*.py")):
            for module, line in imports(path):
                if module.startswith("noetrium_platform.infrastructure.lifecycle.process.capture") or module.startswith("noetrium_platform.capabilities.model.serving") or module.startswith("noetrium_platform.infrastructure.lifecycle.service.runtime"):
                    rows.append(violation(
                        root,
                        path,
                        "process_api_implementation_boundary",
                        line,
                        f"process_api imports implementation/domain package {module}",
                    ))

    service = root / "noetrium_platform" / "infrastructure" / "lifecycle" / "service" / "runtime"
    if service.exists():
        for path in sorted(service.rglob("*.py")):
            for module, line in imports(path):
                if module.startswith("noetrium_platform.capabilities.model.serving"):
                    rows.append(violation(
                        root,
                        path,
                        "service_model_process_boundary",
                        line,
                        f"Service OS imports Model OS implementation {module}; use process_api or another neutral API",
                    ))
                if path.name == "crash_capture.py" and module.startswith("noetrium_platform.infrastructure.lifecycle.process.capture"):
                    rows.append(violation(
                        root,
                        path,
                        "process_capture_backend_boundary",
                        line,
                        "service crash capture imports concrete process capture backend; depend on ProcessByteCapturePort",
                    ))

    model = root / "noetrium_platform" / "capabilities" / "model" / "serving"
    for legacy in (
        "process_capture.py",
        "process_capture_contracts.py",
        "process_capture_fd.py",
        "process_capture_state.py",
        "process_capture_storage.py",
        "process_capture_tail.py",
        "process_capture_writer.py",
    ):
        path = model / legacy
        if path.exists():
            rows.append(violation(
                root,
                path,
                "process_capture_domain_ownership",
                1,
                "generic process capture implementation returned to Model OS; keep it in process_capture/process_api",
            ))
    return rows


__all__ = ["audit_process_invariants"]
