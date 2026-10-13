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
    MachineExecutor,
    ChildMachineSupervisorPort,
    UnitCompiler,
    WorkerAdmission,
    canonical_bytes,
)
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobStorePort
from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority
from noetrium_platform.foundation.kernel.kernel.universal import (
    UNIT_MACHINE_COMMANDS,
    universal_machine_family,
)


def _check_machine_families() -> int:
    family = universal_machine_family()
    if family.family_id != f"unit.machine.v{family.implementation_version}":
        raise SystemExit(
            "Universal Unit Machine family_id drifted: "
            f"{family.family_id}"
        )
    if family.command_kinds != UNIT_MACHINE_COMMANDS:
        raise SystemExit("Universal Unit Machine command ABI drifted")
    if not family.state_schema.startswith("unit.machine-state.v"):
        raise SystemExit("Universal Unit Machine state schema drifted")
    if not family.replay_level.strip():
        raise SystemExit("Universal Unit Machine lacks replay level")
    return 1


def _check_public_facades() -> int:
    violations = audit_registered_public_facades(ROOT)
    if violations:
        detail = "; ".join(f"{row.path}:{row.line} {row.detail}" for row in violations)
        raise SystemExit(f"public facade exposes duplicate authority/concrete layer: {detail}")
    return 0

def _check_research_os_product_entrypoint() -> str:
    """Require the unique downstream surface: NoetriumUnit + run."""

    legacy_paths = (
        ROOT / "noetrium/platform.py",
        ROOT / "noetrium_platform/platform.py",
        ROOT / "noetrium/api",
        ROOT / "noetrium_platform/product/api",
        ROOT / "components/api",
        ROOT / "orchestration/api",
    )
    leaked = tuple(
        str(path.relative_to(ROOT))
        for path in legacy_paths
        if path.exists()
    )
    if leaked:
        raise SystemExit(
            "legacy Level-0 product composition reappeared: " + ", ".join(leaked)
        )

    entrypoint = ROOT / "noetrium/__init__.py"
    stub = ROOT / "noetrium/__init__.pyi"
    if not entrypoint.is_file() or not stub.is_file():
        raise SystemExit("canonical Noetrium public surface is incomplete")

    entry_source = entrypoint.read_text(encoding="utf-8")
    if "import *" in entry_source:
        raise SystemExit("noetrium wildcard imports are forbidden")
    if (
        "from noetrium_platform.foundation.kernel.unit import NoetriumUnit"
        not in entry_source
        or "from noetrium._runtime import run" not in entry_source
    ):
        raise SystemExit(
            "noetrium must bind exactly NoetriumUnit and run"
        )
    entry_tree = ast.parse(entry_source, filename=str(entrypoint))
    declared_all = None
    for node in entry_tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List)):
            raise SystemExit("noetrium __all__ must be a static sequence")
        values = []
        for item in node.value.elts:
            if not isinstance(item, ast.Constant) or type(item.value) is not str:
                raise SystemExit("noetrium __all__ must contain string literals")
            values.append(item.value)
        declared_all = tuple(values)
        break
    if declared_all != ("NoetriumUnit", "run"):
        raise SystemExit(
            "canonical Noetrium public root set drifted: "
            f"{declared_all!r}"
        )
    forbidden_public = (
        "noetrium_platform.platform",
        "components.api",
        "orchestration.api",
    )
    escaped = tuple(value for value in forbidden_public if value in entry_source)
    if escaped:
        raise SystemExit(
            "Noetrium public API contains legacy/lower symbols: "
            + ", ".join(escaped)
        )
    return "noetrium"


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

def _check_research_machine_bypasses() -> int:
    """Retired paper-level runners/state owners must not reappear.

    These checks are deliberately about architectural escape hatches, not class
    naming in general. Infrastructure/provider managers are allowed; research
    semantics must flow through Programs and Machine Journal authority.
    """

    retired_paths = (
        "noetrium_platform/foundation/kernel/kernel/runtime.py",
        "noetrium_platform/research/execution/machines/reference.py",
        "noetrium_platform/capabilities/participant/agent/runtime/action_manager.py",
        "noetrium_platform/capabilities/participant/agent/runtime/coordination.py",
        "noetrium_platform/capabilities/participant/agent/runtime/conversation.py",
        "noetrium_platform/capabilities/participant/agent/runtime/self_prompter.py",
        "noetrium_platform/capabilities/participant/agent/runtime/goals.py",
        "noetrium_platform/capabilities/participant/agent/runtime/modes.py",
        "noetrium_platform/capabilities/participant/agent/runtime/skill_library.py",
        "noetrium_platform/capabilities/participant/agent/api/memory_checkpoint.py",
        "noetrium_platform/capabilities/participant/agent/api/skill_checkpoint.py",
        "noetrium_platform/research/experimentation/run/lifecycle/runtime/state.py",
        "noetrium_platform/research/execution/machines/runtime_program.py",
        "noetrium_platform/research/execution/machines/runtime_host.py",
        "noetrium_platform/research/execution/lifecycle/__init__.py",
        "noetrium_platform/research/execution/lifecycle/contracts.py",
        "noetrium_platform/research/execution/lifecycle/health.py",
        "noetrium_platform/research/execution/lifecycle/manager.py",
        "noetrium_platform/composition/experiment_runtime.py",
        "noetrium_platform/research/execution/machines/composition/host_factory.py",
        "noetrium_platform/research/experimentation/lifecycle/run/runtime/lifecycle_factory.py",
        "noetrium_platform/research/experimentation/lifecycle/run/runtime/lifecycle_closer.py",
        "noetrium_platform/research/experimentation/lifecycle/run/runtime/resources.py",
        "noetrium_platform/research/experimentation/lifecycle/run/api/ports.py",
        "noetrium_platform/research/experimentation/lifecycle/run/api/lifecycle_ports.py",
        "noetrium_platform/research/experimentation/lifecycle/run/providers/__init__.py",
        "noetrium_platform/research/experimentation/lifecycle/run/providers/identity.py",
        "noetrium_platform/research/experimentation/lifecycle/run/api/identity_ports.py",
        "noetrium_platform/research/experimentation/lifecycle/run/runtime/diagnostics.py",
        "noetrium_platform/research/experimentation/lifecycle/run/api/diagnostics.py",
        "noetrium_platform/research/experimentation/lifecycle/experiment/runtime/engine.py",
        "noetrium_platform/research/experimentation/lifecycle/experiment/runtime/trial_cycle.py",
    )
    existing = tuple(path for path in retired_paths if (ROOT / path).exists())
    if existing:
        raise SystemExit(
            "retired research execution authority reappeared: "
            + ", ".join(existing)
        )

    forbidden_symbols = {
        ROOT / "noetrium_platform/research/experimentation/lifecycle/experiment/api/trial_protocol.py": {
            "ExperimentTrialProtocol",
        },
        ROOT / "noetrium_platform/research/experimentation/lifecycle/study/runtime/trial.py": {
            "TrialMatrixExecutor",
        },
    }
    checked = len(retired_paths)
    for path, names in forbidden_symbols.items():
        if not path.is_file():
            # A retired implementation path staying absent is the desired state.
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        declared = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }
        overlap = declared & names
        if overlap:
            raise SystemExit(
                "paper-level execution bypass reappeared in "
                f"{path.relative_to(ROOT)}: {sorted(overlap)}"
            )
        checked += 1

    trial_runtime = (
        ROOT
        / "noetrium_platform/research/execution/workflow/runtime/program_trial.py"
    )
    if not trial_runtime.is_file():
        raise SystemExit("canonical RuntimeProgram Trial adapter is missing")
    source = trial_runtime.read_text(encoding="utf-8")
    if "class RuntimeProgramTrialProtocol" not in source:
        raise SystemExit(
            "canonical Trial execution is not constrained to RuntimeProgram"
        )
    if "BoundExecutableUnit" not in source:
        raise SystemExit(
            "canonical Trial execution bypasses BoundExecutableUnit"
        )
    checked += 1

    nsh = ROOT / "noetrium/nsh.py"
    nsh_source = nsh.read_text(encoding="utf-8")
    retired_nsh_markers = (
        "RunLifecycleInterpreter",
        "machines.reference",
        '"run.start"',
        '"run.pause"',
        '"run.resume"',
        '"run.complete"',
        '"run.fail"',
    )
    leaked = tuple(
        marker for marker in retired_nsh_markers
        if marker in nsh_source
    )
    if leaked:
        raise SystemExit(
            "nsh reintroduced retired Research Run lifecycle authority: "
            + ", ".join(leaked)
        )
    checked += 1
    return checked



def _check_unit_host_unification() -> int:
    """Research semantics must not rebuild the Universal Unit Machine."""

    roots = (
        ROOT / "noetrium_platform/research",
        ROOT / "noetrium_platform/capabilities/participant/agent/runtime/memory.py",
        ROOT / "noetrium_platform/capabilities/participant/agent/runtime/scheduled_messaging.py",
        ROOT / "noetrium_platform/capabilities/environment/runtime/runtime/state_machine.py",
        ROOT / "noetrium_platform/composition/agent_turn_machine.py",
        ROOT / "orchestration/multi_agent/orchestration.py",
    )
    checked = 0
    violations: list[str] = []
    candidates: list[Path] = []
    for root in roots:
        if root.is_file():
            candidates.append(root)
        elif root.is_dir():
            candidates.extend(sorted(root.rglob("*.py")))
    forbidden_calls = {
        "MachineExecutor",
        "UniversalUnitMachine",
        "_UnitDriver",
    }
    for path in candidates:
        if "__pycache__" in path.parts:
            continue
        checked += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            else:
                name = None
            if name in forbidden_calls:
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:{name}"
                )
    if violations:
        raise SystemExit(
            "research layer rebuilt Universal Unit Machine mechanics: "
            + "; ".join(violations)
        )
    return checked


def _check_research_machine_public_surface() -> int:
    """Adjacent research API may expose Unit semantics, never execution engines."""

    facade = ROOT / "noetrium_platform/research/execution/machines/api/__init__.py"
    tree = ast.parse(facade.read_text(encoding="utf-8"), filename=str(facade))
    exports: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            raise SystemExit(
                "research execution API __all__ must be a static sequence"
            )
        for item in node.value.elts:
            if not isinstance(item, ast.Constant) or type(item.value) is not str:
                raise SystemExit(
                    "research execution API __all__ must contain string literals"
                )
            exports.add(item.value)

    forbidden = {
        "MachineProgramBuilder",
        "BoundMachineProgram",
        "MachineProgramOperation",
        "ProgrammableMachineInterpreter",
        "UniversalUnitMachine",
        "MachineExecutor",
        "MachineKind",
        "ProgramLock",
        "MachineProgramRef",
        "PROGRAM_COMMANDS",
        "PROGRAMMABLE_MACHINE_KINDS",
        "programmable_machine_families",
        "programmable_machine_family",
    }
    leaked = tuple(sorted(exports & forbidden))
    if leaked:
        raise SystemExit(
            "research execution API leaks retired/engine internals: "
            + ", ".join(leaked)
        )

    required = {
        "NoetriumUnit",
        "executable_unit",
        "unit_operation",
        "unit_flow",
    }
    missing = tuple(sorted(required - exports))
    if missing:
        raise SystemExit(
            "research execution API is missing Unit-native semantics: "
            + ", ".join(missing)
        )
    return len(exports)


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
            "ProgramLock", "program_lock_digest", "MachineCommand", "RunBinding", "canonicalJson", "sha256Hex",
        ),
        ROOT / "sdk/rust/Cargo.toml": ("noetrium-machine-sdk", "serde"),
        ROOT / "sdk/rust/src/lib.rs": (
            "ProgramLock", "program_lock_digest", "MachineCommand", "RunBinding", "canonical_json", "sha256_hex",
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
        "NoetriumUnit",
        "MachineExecutor",
        "Machine Journal",
        "No global total-order journal",
        "Declared",
        "Authorized",
        "Observed",
        "Evidenced",
        "Effect",
        "Artifact",
        "Evidence",
        "recovery",
        "resource",
        "provider",
    )
    missing = [marker for marker in required if marker not in document]
    if missing:
        raise SystemExit(
            "architecture document/code state mismatch: " + ", ".join(missing)
        )


def _check_unit_only_research_carrier() -> int:
    """Production research semantics must use NoetriumUnit as the sole carrier."""

    retired_paths = (
        ROOT / "noetrium_platform/product/research_portfolio.py",
        ROOT / "noetrium_platform/product/research_graph_codec.py",
    )
    leaked = tuple(
        str(path.relative_to(ROOT))
        for path in retired_paths
        if path.exists()
    )
    if leaked:
        raise SystemExit(
            "retired research carrier/codec implementation reappeared: "
            + ", ".join(leaked)
        )

    forbidden_symbols = {
        "ResearchMethodImplementation",
    }
    forbidden_modules = {
        "noetrium_platform.product.research_portfolio",
        "noetrium_platform.product.research_graph_codec",
    }
    roots = (
        ROOT / "noetrium",
        ROOT / "noetrium_platform",
        ROOT / "research",
        ROOT / "orchestration",
        ROOT / "components",
        ROOT / "scripts",
    )
    violations: list[str] = []
    checked = 0
    self_path = Path(__file__).resolve()
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if path.resolve() == self_path or "__pycache__" in path.parts:
                continue
            checked += 1
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            bad: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in forbidden_symbols:
                    bad.add(node.id)
                elif isinstance(node, ast.Attribute) and node.attr in forbidden_symbols:
                    bad.add(node.attr)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in forbidden_modules:
                            bad.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module in forbidden_modules:
                        bad.add(module)
                    for alias in node.names:
                        if alias.name in forbidden_symbols:
                            bad.add(alias.name)
            if bad:
                violations.append(
                    f"{path.relative_to(ROOT)}:{','.join(sorted(bad))}"
                )
    if violations:
        raise SystemExit(
            "production research carrier escaped NoetriumUnit: "
            + "; ".join(violations)
        )
    return checked


def _check_research_workspace_contract_boundary() -> int:
    """Research-workspace metadata must not become a platform-core authority."""

    retired = (
        ROOT / "noetrium_platform/research/provenance.py",
        ROOT / "noetrium_platform/research/reproduction.py",
    )
    leaked_files = tuple(
        str(path.relative_to(ROOT))
        for path in retired
        if path.exists()
    )
    if leaked_files:
        raise SystemExit(
            "research workspace metadata leaked into platform core: "
            + ", ".join(leaked_files)
        )

    forbidden_imports = (
        "noetrium_platform.research.provenance",
        "noetrium_platform.research.reproduction",
    )
    violations: list[str] = []
    workspace = ROOT / "research"
    checked = 0
    for path in sorted(workspace.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        checked += 1
        source = path.read_text(encoding="utf-8")
        escaped = tuple(
            token
            for token in forbidden_imports
            if token in source
        )
        if escaped:
            violations.append(
                f"{path.relative_to(ROOT)}:{','.join(escaped)}"
            )
    if violations:
        raise SystemExit(
            "research workspace imports retired platform-root metadata contracts: "
            + "; ".join(violations)
        )
    return checked



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict-unclassified", action="store_true")
    args = parser.parse_args()
    catalog_path = ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"
    matrix_path = ROOT / "docs/architecture/OWNERSHIP_MATRIX.json"
    doc_path = ROOT / "docs/architecture/SYSTEM_ARCHITECTURE.md"
    matrix = build_ownership_matrix(load_catalog(catalog_path))
    if not matrix_path.exists():
        raise SystemExit("ownership matrix is missing; run generate_ownership_matrix.py")
    stored = load_catalog(matrix_path)
    if stored.get("schema") != "noetrium.ownership-matrix.v2":
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
    platform_owner = _check_research_os_product_entrypoint()
    durability_owner = _check_durability_ownership()
    worker_count = _check_worker_boundaries()
    research_machine_bypass_checks = _check_research_machine_bypasses()
    unit_host_checks = _check_unit_host_unification()
    research_machine_public_exports = _check_research_machine_public_surface()
    unit_only_research_carrier_checks = _check_unit_only_research_carrier()
    research_workspace_contract_checks = _check_research_workspace_contract_boundary()
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
        "research_machine_bypass_checks": research_machine_bypass_checks,
        "unit_host_checks": unit_host_checks,
        "research_machine_public_exports": research_machine_public_exports,
        "unit_only_research_carrier_checks": unit_only_research_carrier_checks,
        "research_workspace_contract_checks": research_workspace_contract_checks,
        "capability_index": capability_index,
        "sdk_surfaces": sdk_surfaces,
        "qualification_ports": all(callable(value) for value in (
            ExecutionQualificationPort, require_production_qualification,
        )),
        "kernel_exports": all(callable(value) for value in (
            MachineExecutor, MachineConformanceHarness, UnitCompiler, WorkerAdmission,
            ChildMachineSupervisorPort,
        )),
        "artifact_blob_contract": callable(ArtifactBlobStorePort),
        "resource_authorities": callable(UniversalResourceAuthority),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
