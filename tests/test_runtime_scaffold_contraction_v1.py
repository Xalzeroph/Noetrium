from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RETIRED_PACKAGES = (
    "noetrium_platform.infrastructure.reliability.diagnostics.causal",
    "noetrium_platform.infrastructure.reliability.diagnostics.timeline",
    "noetrium_platform.infrastructure.reliability.failure.catalog",
    "noetrium_platform.infrastructure.reliability.failure.descriptor",
    "noetrium_platform.infrastructure.reliability.failure.envelope",
    "noetrium_platform.infrastructure.reliability.failure.fingerprint",
    "noetrium_platform.infrastructure.reliability.failure.materialization",
    "noetrium_platform.infrastructure.reliability.failure.taxonomy",
    "noetrium_platform.infrastructure.reliability.incident",
    "noetrium_platform.infrastructure.reliability.policy",
    "noetrium_platform.infrastructure.reliability.reconciliation",
    "noetrium_platform.infrastructure.reliability.recovery.evidence",
    "noetrium_platform.infrastructure.reliability.recovery.plan",
    "noetrium_platform.infrastructure.reliability.recovery.replay",
    "noetrium_platform.infrastructure.resources.catalog",
)

RETIRED_PACKAGES += (
    "noetrium_platform.infrastructure.lifecycle.control",
    "noetrium_platform.infrastructure.lifecycle.history",
    "noetrium_platform.infrastructure.lifecycle.process.identity",
    "noetrium_platform.infrastructure.lifecycle.process.launch",
    "noetrium_platform.infrastructure.lifecycle.process.lifecycle",
    "noetrium_platform.infrastructure.lifecycle.session.binding",
    "noetrium_platform.infrastructure.lifecycle.session.identity",
    "noetrium_platform.infrastructure.lifecycle.supervision",
)

RETAINED_PARENT_SEAMS = (
    "noetrium_platform/infrastructure/lifecycle/process/api/contracts.py",
    "noetrium_platform/infrastructure/lifecycle/process/supervision/api/contracts.py",
    "noetrium_platform/infrastructure/lifecycle/session/api/contracts.py",
    "noetrium_platform/infrastructure/lifecycle/session/api/binding.py",
    "noetrium_platform/infrastructure/lifecycle/session/runtime/binding.py",
    "noetrium_platform/infrastructure/reliability/diagnostics/runtime/causal_graph.py",
    "noetrium_platform/infrastructure/reliability/diagnostics/runtime/causal_projection.py",
    "noetrium_platform/infrastructure/reliability/failure/api/contracts.py",
    "noetrium_platform/infrastructure/reliability/failure/api/catalog.py",
    "noetrium_platform/infrastructure/reliability/failure/api/fingerprint.py",
    "noetrium_platform/infrastructure/reliability/effect/api/transitions.py",
    "noetrium_platform/infrastructure/reliability/recovery/api/contracts.py",
    "noetrium_platform/infrastructure/resources/compute/api/contracts.py",
    "noetrium_platform/infrastructure/resources/lease/api/contracts.py",
)
def test_role02_generated_scaffold_packages_are_absent() -> None:
    for package in RETIRED_PACKAGES:
        path = ROOT.joinpath(*package.split("."))
        assert not any(path.rglob("*.py")), package
        assert not (path / "api" / "boundary.py").exists(), package


def test_role02_real_parent_authority_seams_remain() -> None:
    for relative in RETAINED_PARENT_SEAMS:
        path = ROOT / relative
        assert path.is_file(), relative
        text = path.read_text(encoding="utf-8")
        assert "SystemLeafContract" not in text, relative


def test_platform_source_does_not_import_retired_role02_shells() -> None:
    offenders: list[tuple[str, str]] = []
    retired = RETIRED_PACKAGES
    for path in (ROOT / "noetrium_platform").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
        for module in modules:
            if any(module == prefix or module.startswith(prefix + ".") for prefix in retired):
                offenders.append((path.relative_to(ROOT).as_posix(), module))
    assert offenders == []
