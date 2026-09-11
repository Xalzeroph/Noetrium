from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.foundation.governance.architecture.api import (
    ExecutionQualificationPort,
    require_production_qualification,
)
from noetrium_platform.foundation.governance.architecture.capability_index import (
    build_capability_index,
    load_capability_index,
)
from noetrium_platform.foundation.governance.architecture.ownership_matrix import (
    build_ownership_matrix,
    load_catalog,
)
from noetrium_platform.foundation.governance.architecture.public_api_invariants import (
    audit_registered_public_facades,
)
from noetrium_platform.foundation.kernel.kernel import (
    MachineConformanceHarness,
    MachineRuntime,
    ResourceSchedulerPort,
    ChildMachineSupervisorPort,
    ContentAddressedStorePort,
    NshCompiler,
    WorkerAdmission,
    canonical_bytes,
)
from noetrium_platform.research.execution.machines.reference import (
    reference_machine_families,
)


def _check_machine_families() -> int:
    families = reference_machine_families()
    if not families:
        raise SystemExit("no executable machine family descriptors are registered")
    family_ids = [family.family_id for family in families]
    kinds = [family.kind for family in families]
    if len(set(family_ids)) != len(family_ids):
        raise SystemExit("machine family ids are duplicated")
    if len(set(kinds)) != len(kinds):
        raise SystemExit("machine family kinds have duplicate implementations")
    for family in families:
        if not family.implementation_version.strip():
            raise SystemExit(f"machine family lacks implementation version: {family.family_id}")
        if not family.state_schema.strip():
            raise SystemExit(f"machine family lacks state schema: {family.family_id}")
        if not family.replay_level.strip():
            raise SystemExit(f"machine family lacks replay level: {family.family_id}")
    return len(families)


def _check_public_facades() -> int:
    violations = audit_registered_public_facades(ROOT)
    if violations:
        detail = "; ".join(f"{row.path}:{row.line} {row.detail}" for row in violations)
        raise SystemExit(f"public facade exposes duplicate authority/concrete layer: {detail}")
    return 0

def _check_public_platform_entrypoint() -> str:
    """Keep the root product entrypoint as a forwarding surface only."""

    entrypoint = ROOT / "noetrium/platform.py"
    owner = "noetrium_platform.platform"
    if not entrypoint.is_file():
        raise SystemExit("public product entrypoint is missing: noetrium/platform.py")
    tree = ast.parse(entrypoint.read_text(encoding="utf-8"), filename=str(entrypoint))
    definitions = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if definitions:
        raise SystemExit(
            "noetrium/platform.py must not define product behavior; "
            "use the single operator composition owner"
        )
    imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)]
    if not any(node.module == owner and any(alias.name == "*" for alias in node.names) for node in imports):
        raise SystemExit("noetrium/platform.py does not forward the operator composition owner")
    if not any(node.module == owner and any(alias.name == "__all__" for alias in node.names) for node in imports):
        raise SystemExit("noetrium/platform.py does not forward the owner's export contract")
    if not (ROOT / "noetrium_platform/platform.py").is_file():
        raise SystemExit("platform composition owner is missing")
    return owner


def _check_durability_ownership() -> str:
    """Artifact publication must reuse the kernel durability authority."""

    path = ROOT / "noetrium_platform/evidence/artifact/content/providers/_publication.py"
    if not path.is_file():
        raise SystemExit("artifact publication durability adapter is missing")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden_imports = {"fcntl", "ctypes", "msvcrt", "threading"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported = {alias.name.split(".", 1)[0] for alias in node.names}
            if imported & forbidden_imports:
                raise SystemExit(
                    "artifact publication must not define a second durability implementation"
                )
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".", 1)[0] in forbidden_imports:
            raise SystemExit(
                "artifact publication must not define a second durability implementation"
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            raise SystemExit(
                "artifact publication must not define a second durability implementation"
            )
        elif isinstance(node, ast.ClassDef):
            methods = [
                child for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            if (
                node.name != "PublicationLock"
                or len(methods) != 1
                or methods[0].name != "__init__"
            ):
                raise SystemExit(
                    "artifact publication must not define a second durability implementation"
                )
    required = (
        "noetrium_platform.foundation.kernel.kernel.durability.durable_file",
        "noetrium_platform.foundation.kernel.kernel.durability.file_lock",
    )
    imported_modules = {
        node.module for node in tree.body
        if isinstance(node, ast.ImportFrom)
    }
    if not all(module in imported_modules for module in required):
        raise SystemExit("artifact publication does not delegate to kernel durability")
    return "noetrium_platform.foundation.kernel.kernel.durability"


def _worker_source_paths() -> tuple[Path, ...]:
    paths: list[Path] = []
    for path in sorted(ROOT.rglob("*.py")):
        if "tests" in path.parts or "scripts" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        named_worker = any(
            isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and "worker" in node.name.lower()
            for node in ast.walk(tree)
        )
        if "worker" in path.name.lower() or named_worker:
            paths.append(path)
    return tuple(paths)


def _check_worker_boundaries() -> int:
    forbidden_modules = ("journal", "snapshot", "outbox", "effect_intent")
    forbidden_calls = {
        "append", "save", "enqueue", "accept", "mark",
        "record_result", "record_reconciled", "record_consumed", "record_not_applied",
    }
    violations: list[str] = []
    paths = _worker_source_paths()
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append(f"{path}: syntax error: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(token in alias.name.lower() for token in forbidden_modules):
                        violations.append(f"{path}:{node.lineno} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if any(token in module.lower() for token in forbidden_modules):
                    violations.append(f"{path}:{node.lineno} imports {module}")
                if any(alias.name.lower() in forbidden_modules for alias in node.names):
                    violations.append(f"{path}:{node.lineno} imports a forbidden authority")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                receiver = ast.unparse(node.func.value).lower()
                authority_receiver = any(token in receiver for token in forbidden_modules)
                if node.func.attr in forbidden_calls and authority_receiver:
                    violations.append(f"{path}:{node.lineno} calls {node.func.attr}()")
    if violations:
        raise SystemExit("worker direct fact-write boundary violated: " + "; ".join(violations))
    return len(paths)

def _check_capability_index() -> str:
    path = ROOT / "docs/architecture/CAPABILITY_INDEX.json"
    if not path.exists():
        raise SystemExit("capability index is missing; run generate_capability_index.py")
    stored = load_capability_index(path)
    expected = build_capability_index(ROOT)
    if canonical_bytes(stored) != canonical_bytes(expected):
        raise SystemExit("capability index drift; regenerate the derived index")
    return str(path.relative_to(ROOT))


def _check_sdk_surfaces() -> tuple[str, ...]:
    required = {
        ROOT / "sdk/typescript/package.json": ("@noetrium/machine-sdk", "src/index.ts"),
        ROOT / "sdk/typescript/src/index.ts": (
            "ProgramLock", "MachineCommand", "RunBinding", "canonicalJson", "sha256Hex",
        ),
        ROOT / "sdk/rust/Cargo.toml": ("noetrium-machine-sdk", "serde"),
        ROOT / "sdk/rust/src/lib.rs": (
            "ProgramLock", "MachineCommand", "RunBinding", "canonical_json", "sha256_hex",
        ),
    }
    missing: list[str] = []
    for path, markers in required.items():
        if not path.exists():
            missing.append(str(path.relative_to(ROOT)))
            continue
        content = path.read_text(encoding="utf-8")
        missing.extend(
            f"{path.relative_to(ROOT)}:{marker}"
            for marker in markers
            if marker not in content
        )
    if missing:
        raise SystemExit("SDK surface is incomplete: " + ", ".join(missing))
    return tuple(str(path.relative_to(ROOT)) for path in required)


def _check_document(doc_path: Path) -> None:
    document = doc_path.read_text(encoding="utf-8")
    required = (
        "## 51. R8",
        "## 52. R9",
        "MachineRuntime",
        "MachineRuntime.replay",
        "JournalInspectionService",
        "PluginManifest",
        "RunBinding",
        "ExecutionQualificationPort",
        "ResourceSchedulerPort",
        "ChildMachineSupervisorPort",
        "ContentAddressedStorePort",
        "RunArtifactStorePort",
        "EvidenceBundle",
        "EffectIntentJournal",
        "UNKNOWN",
        "Ownership Matrix",
        "## 59. R16",
        "CAPABILITY_INDEX.json",
        "DirectoryResourceScheduler",
        "DirectoryChildMachineSupervisor",
        "## 66. R23",
        "## 63. R20",
        "## 65. R22",
    )
    missing = [marker for marker in required if marker not in document]
    if missing:
        raise SystemExit("architecture document/code state mismatch: " + ", ".join(missing))

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict-unclassified", action="store_true")
    args = parser.parse_args()
    catalog_path = ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"
    matrix_path = ROOT / "docs/architecture/OWNERSHIP_MATRIX.json"
    doc_path = ROOT / "docs/architecture/NOETRIUM_RESEARCH_OS_END_STATE_ARCHITECTURE.md"
    matrix = build_ownership_matrix(load_catalog(catalog_path))
    if not matrix_path.exists():
        raise SystemExit("ownership matrix is missing; run generate_ownership_matrix.py")
    stored = load_catalog(matrix_path)
    if stored.get("schema") != "noetrium.ownership-matrix.v1":
        raise SystemExit("ownership matrix schema is invalid")
    if stored.get("source_digest") != matrix.source_digest:
        raise SystemExit("ownership matrix source catalog digest drift")
    if stored.get("matrix_digest") != matrix.matrix_digest:
        raise SystemExit("ownership matrix digest drift; regenerate the derived matrix")
    expected_rows = [row.as_dict() for row in matrix.rows]
    if canonical_bytes(stored.get("rows")) != canonical_bytes(expected_rows):
        raise SystemExit("ownership matrix rows drift; regenerate the derived matrix")
    if args.strict_unclassified and any(row.audit_required for row in matrix.rows):
        raise SystemExit("ownership matrix contains explicitly unclassified fields")
    _check_document(doc_path)
    family_count = _check_machine_families()
    facade_count = _check_public_facades()
    platform_owner = _check_public_platform_entrypoint()
    durability_owner = _check_durability_ownership()
    worker_count = _check_worker_boundaries()
    capability_index = _check_capability_index()
    sdk_surfaces = _check_sdk_surfaces()
    print(json.dumps({
        "systems": len(matrix.rows),
        "matrix_digest": matrix.matrix_digest,
        "unclassified_rows": sum(bool(row.audit_required) for row in matrix.rows),
        "machine_families": family_count,
        "facade_violations": facade_count,
        "public_platform_owner": platform_owner,
        "durability_owner": durability_owner,
        "worker_modules_checked": worker_count,
        "capability_index": capability_index,
        "sdk_surfaces": sdk_surfaces,
        "qualification_ports": all(callable(value) for value in (
            ExecutionQualificationPort, require_production_qualification,
        )),
        "kernel_exports": all(callable(value) for value in (
            MachineRuntime, MachineConformanceHarness, NshCompiler, WorkerAdmission,
            ResourceSchedulerPort, ChildMachineSupervisorPort, ContentAddressedStorePort,
        )),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
