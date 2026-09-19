"""Default programmable EvaluationMachine presets.

Evaluation policy is not a fixed platform loop. This module provides one
paired-comparison preset over the universal Program/Rule/Machine substrate;
papers may replace the rules, operations, aggregation, judges, or calibration
without changing the kernel.
"""
from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineKind,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.machines import (
    EvaluationConcern,
    ProgramHandlerRegistry,
    ProgramNodeRequest,
    ProgramNodeResult,
    ProgramRule,
    ProgramRuleSet,
    ResearchProgram,
    ResearchProgramHost,
    RuleDispatchMode,
    UnhandledEventPolicy,
    build_rule_handlers,
    compile_rule_program,
)
from noetrium_platform.research.experimentation.evaluation.api import (
    BranchReceipt,
    ComparabilityProof,
    build_comparability_proof,
)


def paired_evaluation_rule_set() -> ProgramRuleSet:
    return ProgramRuleSet(
        (
            ProgramRule(
                "compare",
                "evaluation.compare",
                "evaluation.paired.compare",
                priority=100,
                semantic=EvaluationConcern.COMPARISON.value,
            ),
            ProgramRule(
                "aggregate",
                "evaluation.aggregate",
                "evaluation.paired.aggregate",
                priority=100,
                semantic=EvaluationConcern.AGGREGATION.value,
            ),
            ProgramRule(
                "finalize",
                "evaluation.finalize",
                "evaluation.paired.finalize",
                priority=100,
                semantic=EvaluationConcern.FINALIZATION.value,
            ),
        ),
        mode=RuleDispatchMode.FIRST,
        unhandled=UnhandledEventPolicy.ERROR,
    )


def compile_paired_evaluation_program(
    *,
    program_id: str = "evaluation.paired.default",
    version: str = "1",
) -> ResearchProgram:
    return compile_rule_program(
        program_id=program_id,
        kind=MachineKind.EVALUATION,
        version=version,
        state_schema="evaluation.paired.state.v1",
        rules=paired_evaluation_rule_set(),
    )


def paired_evaluation_initial_data(
    *,
    evaluation_id: str,
    source_execution_digest: str,
) -> JsonObject:
    if type(evaluation_id) is not str or not evaluation_id.strip():
        raise ValueError("evaluation_id is required")
    if (
        type(source_execution_digest) is not str
        or len(source_execution_digest) != 64
        or any(ch not in "0123456789abcdef" for ch in source_execution_digest)
    ):
        raise ValueError("source_execution_digest must be lowercase SHA-256")
    return {
        "evaluation_id": evaluation_id,
        "source_execution_digest": source_execution_digest,
        "pairs": {},
        "aggregate": {},
        "comparison_count": 0,
        "valid_comparison_count": 0,
    }


def _payload(request: ProgramNodeRequest) -> dict[str, JsonValue]:
    decoded = thaw_json(request.payload)
    if not isinstance(decoded, dict):
        raise TypeError("evaluation event payload must be an object")
    return decoded


def _data(request: ProgramNodeRequest) -> dict[str, JsonValue]:
    decoded = thaw_json(request.data)
    if not isinstance(decoded, dict):
        raise TypeError("evaluation program data must be an object")
    return decoded


def _receipt(value: JsonObject) -> BranchReceipt:
    if not isinstance(value, Mapping):
        raise TypeError("paired evaluation branch receipt must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError("paired evaluation branch receipt must decode to an object")
    metrics = decoded.get("metrics")
    if not isinstance(metrics, (tuple, list)):
        raise TypeError("paired evaluation metrics must be a sequence")
    metric_rows: list[tuple[str, float]] = []
    for row in metrics:
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            raise TypeError("paired evaluation metric row must have two entries")
        metric_rows.append((str(row[0]), float(row[1])))
    return BranchReceipt(
        branch_id=decoded["branch_id"],
        source_checkpoint_id=decoded["source_checkpoint_id"],
        workload_id=decoded["workload_id"],
        environment_generation=decoded["environment_generation"],
        task_manifest_digest=decoded["task_manifest_digest"],
        branch_writes=tuple(decoded.get("branch_writes", ())),
        lifetime_writes=tuple(decoded.get("lifetime_writes", ())),
        private_to_method_flows=tuple(decoded.get("private_to_method_flows", ())),
        metrics=tuple(metric_rows),
    )


def _receipt_payload(receipt: BranchReceipt) -> JsonObject:
    return {
        "branch_id": receipt.branch_id,
        "source_checkpoint_id": receipt.source_checkpoint_id,
        "workload_id": receipt.workload_id,
        "environment_generation": receipt.environment_generation,
        "task_manifest_digest": receipt.task_manifest_digest,
        "branch_writes": receipt.branch_writes,
        "lifetime_writes": receipt.lifetime_writes,
        "private_to_method_flows": receipt.private_to_method_flows,
        "metrics": receipt.metrics,
    }


def _proof_payload(proof: ComparabilityProof) -> JsonObject:
    return {
        "valid": proof.valid,
        "pair_id": proof.pair_id,
        "violations": proof.violations,
        "source_checkpoint_id": proof.source_checkpoint_id,
        "workload_id": proof.workload_id,
        "environment_generation": proof.environment_generation,
        "task_manifest_digest": proof.task_manifest_digest,
    }


def paired_evaluation_operations() -> ProgramHandlerRegistry:
    operations = ProgramHandlerRegistry()

    def compare(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        control_value = payload.get("control")
        candidate_value = payload.get("candidate")
        if not isinstance(control_value, Mapping) or not isinstance(candidate_value, Mapping):
            raise TypeError("evaluation.compare requires control/candidate objects")
        control = _receipt(control_value)
        candidate = _receipt(candidate_value)
        proof = build_comparability_proof(control, candidate)

        control_metrics = dict(control.metrics)
        candidate_metrics = dict(candidate.metrics)
        deltas: tuple[tuple[str, float], ...] = ()
        if proof.valid:
            deltas = tuple(
                (name, candidate_metrics[name] - control_metrics[name])
                for name in sorted(control_metrics)
            )

        pairs_value = data.get("pairs", {})
        if not isinstance(pairs_value, Mapping):
            raise TypeError("evaluation pairs state must be an object")
        pairs = dict(pairs_value)
        pair_payload: JsonObject = {
            "control": _receipt_payload(control),
            "candidate": _receipt_payload(candidate),
            "proof": _proof_payload(proof),
            "metric_deltas": deltas,
        }
        existing = pairs.get(proof.pair_id)
        if existing is not None and canonical_digest(existing) != canonical_digest(pair_payload):
            raise ValueError("evaluation pair identity was reused with drift")
        pairs[proof.pair_id] = pair_payload

        comparison_count = data.get("comparison_count", 0)
        valid_count = data.get("valid_comparison_count", 0)
        if type(comparison_count) is not int or type(valid_count) is not int:
            raise TypeError("evaluation comparison counters must be integers")
        if existing is None:
            comparison_count += 1
            if proof.valid:
                valid_count += 1

        return ProgramNodeResult(
            value={
                "pair_id": proof.pair_id,
                "valid": proof.valid,
                "violations": proof.violations,
                "metric_deltas": deltas,
            },
            state_update={
                "pairs": pairs,
                "comparison_count": comparison_count,
                "valid_comparison_count": valid_count,
            },
            events=({
                "type": "evaluation_pair_compared",
                "pair_id": proof.pair_id,
                "valid": proof.valid,
                "violations": proof.violations,
            },),
        )

    def aggregate(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        pairs_value = data.get("pairs", {})
        if not isinstance(pairs_value, Mapping):
            raise TypeError("evaluation pairs state must be an object")
        totals: dict[str, float] = {}
        counts: dict[str, int] = {}
        valid_pair_ids: list[str] = []
        for pair_id, pair_value in pairs_value.items():
            if type(pair_id) is not str or not isinstance(pair_value, Mapping):
                raise TypeError("evaluation pair state is malformed")
            proof = pair_value.get("proof")
            deltas = pair_value.get("metric_deltas", ())
            if not isinstance(proof, Mapping) or proof.get("valid") is not True:
                continue
            if not isinstance(deltas, (tuple, list)):
                raise TypeError("evaluation metric_deltas must be a sequence")
            valid_pair_ids.append(pair_id)
            for row in deltas:
                if not isinstance(row, (tuple, list)) or len(row) != 2:
                    raise TypeError("evaluation metric delta row is malformed")
                name = str(row[0])
                delta = float(row[1])
                totals[name] = totals.get(name, 0.0) + delta
                counts[name] = counts.get(name, 0) + 1
        aggregate: JsonObject = {
            "valid_pair_ids": tuple(sorted(valid_pair_ids)),
            "mean_metric_deltas": tuple(
                (name, totals[name] / counts[name])
                for name in sorted(totals)
            ),
            "valid_pair_count": len(valid_pair_ids),
        }
        return ProgramNodeResult(
            value=aggregate,
            state_update={"aggregate": aggregate},
            events=({
                "type": "evaluation_aggregated",
                "valid_pair_count": len(valid_pair_ids),
            },),
        )

    def finalize(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        aggregate = data.get("aggregate", {})
        if not isinstance(aggregate, Mapping):
            raise TypeError("evaluation aggregate must be an object")
        result_digest = canonical_digest({
            "evaluation_id": data.get("evaluation_id"),
            "source_execution_digest": data.get("source_execution_digest"),
            "pairs": data.get("pairs", {}),
            "aggregate": aggregate,
        })
        return ProgramNodeResult(
            value={
                "result_digest": result_digest,
                "aggregate": aggregate,
                "comparison_count": data.get("comparison_count", 0),
                "valid_comparison_count": data.get("valid_comparison_count", 0),
            },
            state_update={"result_digest": result_digest},
            status=MachineStatus.COMPLETED,
            events=({
                "type": "evaluation_finalized",
                "result_digest": result_digest,
            },),
        )

    operations.register(
        "evaluation.paired.compare",
        compare,
        implementation_digest=canonical_digest({
            "operation": "evaluation.paired.compare",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "evaluation.paired.aggregate",
        aggregate,
        implementation_digest=canonical_digest({
            "operation": "evaluation.paired.aggregate",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "evaluation.paired.finalize",
        finalize,
        implementation_digest=canonical_digest({
            "operation": "evaluation.paired.finalize",
            "implementation_revision": 1,
        }),
    )
    return operations


def paired_evaluation_handlers() -> ProgramHandlerRegistry:
    return build_rule_handlers(
        paired_evaluation_rule_set(),
        paired_evaluation_operations(),
    )


def paired_evaluation_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    """Default paired EvaluationProgram host."""
    program = compile_paired_evaluation_program()
    return ResearchProgramHost(
        host_id="evaluation.paired.default",
        program=program,
        journal=journal,
        snapshot_store=snapshot_store,
        base_handlers=paired_evaluation_handlers(),
        dependency_identity={
            "rule_set_digest": paired_evaluation_rule_set().rule_set_digest,
        },
    )


__all__ = [
    "compile_paired_evaluation_program",
    "paired_evaluation_handlers",
    "paired_evaluation_host",
    "paired_evaluation_initial_data",
    "paired_evaluation_operations",
    "paired_evaluation_rule_set",
]
