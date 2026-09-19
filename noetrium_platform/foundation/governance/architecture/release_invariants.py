from __future__ import annotations

from pathlib import Path

from .source_scan import SourceInvariantViolation, imports, violation


def _audit_release_quiescence_boundary(root: Path) -> list[SourceInvariantViolation]:
    path = root / "noetrium_platform" / "foundation" / "governance" / "release" / "composition" / "retirement.py"
    if not path.exists():
        return []
    forbidden = (
        "noetrium_platform.infrastructure.lifecycle.session.runtime",
        "noetrium_platform.infrastructure.lifecycle.launch_control",
        "noetrium_platform.infrastructure.lifecycle.service.runtime",
        "noetrium_platform.capabilities.model.serving",
    )
    rows: list[SourceInvariantViolation] = []
    for module, line in imports(path):
        if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
            rows.append(violation(
                root,
                path,
                "release_quiescence_backend_firewall",
                line,
                f"release verifier imports operational backend {module}; use ReleaseConsumerQuiescenceProbe",
            ))
    return rows


def _audit_runtime_release_verification_boundary(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    runtime_manager = root / "noetrium_platform" / "research" / "execution" / "runtime" / "manager"
    for path in runtime_manager.glob("*.py"):
        for module, line in imports(path):
            if module == "noetrium_platform.foundation.governance.release.runtime" or module.startswith("noetrium_platform.foundation.governance.release.runtime."):
                rows.append(violation(
                    root,
                    path,
                    "release_verification_backend_firewall",
                    line,
                    f"runtime manager imports release implementation {module}; depend on release_api evidence ports",
                ))
    return rows


def _audit_release_quality_boundary(root: Path) -> list[SourceInvariantViolation]:
    release = root / "noetrium_platform" / "foundation" / "governance" / "release" / "runtime"
    if not release.exists():
        return []
    rows: list[SourceInvariantViolation] = []
    forbidden = ("noetrium_platform.foundation.governance.architecture", "noetrium_platform.foundation.governance.quality")
    for path in sorted(release.rglob("*.py")):
        for module, line in imports(path):
            if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                rows.append(violation(
                    root,
                    path,
                    "release_quality_evidence_boundary",
                    line,
                    f"Release implementation runs architecture/quality subsystem {module}; consume ReleaseQualityEvidence from composition",
                ))
    return rows



def _audit_release_freeze_single_truth(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    for legacy in ("PACKAGE_CONTENTS.sha256", "PACKAGE_METADATA.json"):
        path = root / legacy
        if path.exists():
            rows.append(violation(
                root, path, "release_freeze_single_truth", 1,
                f"legacy package snapshot authority {legacy} must not coexist with RELEASE_MANIFEST/RELEASE_EVIDENCE",
            ))
    for script_name in ("generate_release_evidence.py", "verify_release_evidence.py", "release_package.py"):
        path = root / "scripts" / script_name
        if not path.exists():
            continue
        for module, line in imports(path):
            if module == "noetrium_platform.foundation.governance.release.runtime":
                rows.append(violation(
                    root, path, "release_script_boundary", line,
                    "official release script imports obsolete release package-root façade",
                ))
    return rows


def audit_release_invariants(root: Path) -> list[SourceInvariantViolation]:
    return (
        _audit_release_quiescence_boundary(root)
        + _audit_runtime_release_verification_boundary(root)
        + _audit_release_quality_boundary(root)
        + _audit_release_freeze_single_truth(root)
    )


__all__ = ["audit_release_invariants"]
