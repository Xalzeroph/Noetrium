#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True, slots=True)
class ReadinessCriterion:
    name: str
    passed: bool
    evidence: dict[str, object]


@dataclass(frozen=True, slots=True)
class ResearchOSScaleReadiness:
    schema: str
    claim_ready: bool
    criteria: tuple[ReadinessCriterion, ...]


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_readiness_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load readiness dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _architecture_topology() -> ReadinessCriterion:
    report = _load_script("audit_system_integration").build_report()
    evidence = {
        "system_count": report["system_count"],
        "component_count": report["component_count"],
        "internal_facet_count": report["internal_facet_count"],
        "disconnected_system_count": report["disconnected_system_count"],
        "layer_disconnected_count": report["layer_disconnected_count"],
        "topology_errors": list(report["topology_errors"]),
    }
    passed = (
        report["disconnected_system_count"] == 0
        and report["layer_disconnected_count"] == 0
        and not report["topology_errors"]
    )
    return ReadinessCriterion("architecture_topology", passed, evidence)


def _workflow_policy() -> ReadinessCriterion:
    errors = tuple(_load_script("canonical_workflow_policy_gate").validate())
    return ReadinessCriterion(
        "canonical_workflow_policy",
        not errors,
        {"errors": list(errors)},
    )


def _projection_clean() -> ReadinessCriterion:
    completed = subprocess.run(
        [sys.executable, "scripts/sync_architecture_maps.py", "--check"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return ReadinessCriterion(
        "architecture_projection_clean",
        completed.returncode == 0,
        {
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-2000:],
            "stderr_tail": completed.stderr[-2000:],
        },
    )


def _no_degradation() -> ReadinessCriterion:
    from noetrium_platform.foundation.governance.architecture.gating.quality import (
        scan_no_degradation,
    )

    findings = scan_no_degradation(ROOT)
    return ReadinessCriterion(
        "no_degradation",
        not findings,
        {
            "finding_count": len(findings),
            "findings": [
                {
                    "kind": row.kind,
                    "path": str(row.path),
                    "line": row.line,
                    "identifier": row.identifier,
                }
                for row in findings[:50]
            ],
        },
    )


def _no_compatibility_surface() -> ReadinessCriterion:
    errors = tuple(_load_script("no_compatibility_surface_gate").validate())
    return ReadinessCriterion(
        "no_compatibility_surface",
        not errors,
        {"errors": list(errors)},
    )


def _call_leaf(call: ast.Call) -> str | None:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _unmanaged_executor_constructors() -> ReadinessCriterion:
    allowed = (
        ROOT
        / "noetrium_platform"
        / "foundation"
        / "kernel"
        / "concurrency"
        / "providers"
    )
    findings: list[dict[str, object]] = []
    for path in sorted((ROOT / "noetrium_platform").rglob("*.py")):
        if path.is_relative_to(allowed):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            findings.append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "line": 0,
                    "constructor": "parse-error",
                    "error": type(exc).__name__,
                }
            )
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            leaf = _call_leaf(node)
            if leaf not in {"ThreadPoolExecutor", "ProcessPoolExecutor"}:
                continue
            findings.append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "line": node.lineno,
                    "constructor": leaf,
                }
            )
    return ReadinessCriterion(
        "single_execution_resource_authority",
        not findings,
        {"unmanaged_executor_constructors": findings},
    )


def _canonical_graph_resource_binding() -> ReadinessCriterion:
    paths = (
        ROOT / "noetrium_platform/composition/research_graph.py",
        ROOT / "noetrium_platform/composition/research_campaign.py",
    )
    violations: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(ROOT))
        if "execution_pool or ResearchExecutionPool()" in text:
            violations.append(f"{rel}: hidden execution-pool fallback")
        if "execution_pool: ResearchExecutionPool," not in text:
            violations.append(f"{rel}: explicit ResearchExecutionPool binding missing")
    graph_text = paths[0].read_text(encoding="utf-8")
    if "time.sleep(" in graph_text:
        violations.append(
            "noetrium_platform/composition/research_graph.py: scheduler polling sleep"
        )
    return ReadinessCriterion(
        "canonical_graph_resource_binding",
        not violations,
        {"violations": violations},
    )


_SCALE_EXECUTION_TESTS = (
    "tests/test_research_graph_scheduler_durable_v1.py",
    "tests/test_research_graph_scale_v1.py",
    "tests/test_research_graph_frontier_v1.py",
    "tests/test_research_graph_claim_control_fence_v1.py",
    "tests/test_research_graph_cut_switch_fence_v1.py",
    "tests/test_research_os_multi_program_selection_v1.py",
    "tests/test_research_os_retry_scope_v1.py",
    "tests/test_research_os_migration_v1.py",
    "tests/test_research_os_migration_node_control_intent_v1.py",
    "tests/test_research_os_artifact_migration_v1.py",
)


def _scale_execution_proof() -> ReadinessCriterion:
    command = (
        sys.executable,
        "-m",
        "pytest",
        "-q",
        *_SCALE_EXECUTION_TESTS,
    )
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        return ReadinessCriterion(
            "scale_execution_proof",
            False,
            {
                "tests": list(_SCALE_EXECUTION_TESTS),
                "timeout_seconds": 180,
                "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
                "stderr_tail": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
            },
        )
    return ReadinessCriterion(
        "scale_execution_proof",
        completed.returncode == 0,
        {
            "tests": list(_SCALE_EXECUTION_TESTS),
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
        },
    )


def _durable_execution_contract() -> ReadinessCriterion:
    from noetrium_platform.research.execution.graph.providers import (
        SQLiteResearchGraphExecutionStore,
    )

    required = (
        "ensure_execution",
        "snapshot",
        "node_state",
        "recover_expired",
        "mark_ready",
        "claim",
        "mark_running",
        "renew_lease",
        "mark_succeeded",
        "mark_failed",
        "retry_failed_subgraph",
        "resolve_reconciliation",
        "mark_reused",
        "reuse_record",
        "active_cut",
        "move_active_cut",
        "control_state",
        "request_drain",
        "pause_if_quiescent",
        "interrupt",
        "cancel_if_quiescent",
        "require_recovery",
        "settle_recovery",
        "node_control_state",
        "node_control_snapshot",
        "request_node_drain",
        "pause_node_if_quiescent",
        "resume_node",
        "interrupt_node",
        "settle_node_recovery",
        "cancel_node_subgraph",
    )
    missing = tuple(
        name for name in required
        if not callable(getattr(SQLiteResearchGraphExecutionStore, name, None))
    )
    source = (
        ROOT
        / "noetrium_platform/research/execution/graph/providers/sqlite.py"
    ).read_text(encoding="utf-8")
    invariants = {
        "wal": 'PRAGMA journal_mode=WAL' in source,
        "synchronous_full": 'PRAGMA synchronous=FULL' in source,
        "immediate_transactions": 'BEGIN IMMEDIATE' in source,
        "active_cut_expected_cas": "expected_cut_id" in source,
        "active_cut_source_fence": "source_fence" in source,
        "claim_graph_control_fence": "claim requires active graph control" in source,
        "claim_node_control_fence": "claim requires active node control" in source,
        "schema_migration_forbidden": "automatic compatibility migration is forbidden"
        in source,
    }
    passed = not missing and all(invariants.values())
    return ReadinessCriterion(
        "durable_execution_contract",
        passed,
        {"missing_methods": list(missing), "invariants": invariants},
    )


def evaluate() -> ResearchOSScaleReadiness:
    criteria = (
        _architecture_topology(),
        _workflow_policy(),
        _projection_clean(),
        _no_degradation(),
        _no_compatibility_surface(),
        _unmanaged_executor_constructors(),
        _canonical_graph_resource_binding(),
        _durable_execution_contract(),
        _scale_execution_proof(),
    )
    return ResearchOSScaleReadiness(
        schema="noetrium.research-os-scale-readiness.v1",
        claim_ready=all(row.passed for row in criteria),
        criteria=criteria,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    receipt = evaluate()
    document = json.dumps(
        asdict(receipt),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding="utf-8")
    print(document, end="")
    return 0 if receipt.claim_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
