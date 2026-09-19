"""Program-backed trial execution over compiled research plans."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from noetrium_platform.evidence.artifact.reference.api import ArtifactReference
from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineJournalPort,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.research.execution.machines import (
    ExperimentConcern,
    ExperimentProgramBuilder,
    ProgramHandlerRegistry,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchMachineSession,
    ResearchProgram,
    ResearchProgramHost,
)
from noetrium_platform.research.experimentation.identity import OptionalIdentityFacet
from noetrium_platform.research.experimentation.study.api import (
    MeasurementContentReference,
    MeasurementRecord,
    MeasurementValue,
    MeasurementValueKind,
    TaskVerifierPort,
    TaskVerifierReceipt,
    TaskVerifierRequest,
    TrialExecutionReceipt,
    TrialExecutionRequest,
    TrialExecutionStageReceipt,
    TrialMatrixExecutionReport,
    TrialProviderPort,
)
from noetrium_platform.research.experimentation.api.research_compiler import CompiledResearchPlan


def _require_measurements(
    plan: CompiledResearchPlan,
    request: TrialExecutionRequest,
    receipt: TrialExecutionReceipt,
) -> tuple[MeasurementRecord, ...]:
    if receipt.request_digest != request.request_digest:
        raise ValueError("trial receipt does not bind the execution request")
    if receipt.assignment_digest != request.assignment.assignment_digest:
        raise ValueError("trial receipt does not bind the assignment")

    task = request.task
    package = None if task is None else task.package
    verifier_required = package is not None and package.verifier_requirement_id is not None
    if verifier_required:
        verifier = receipt.verifier_receipt
        if verifier is None:
            raise ValueError("task package declares verifier but trial receipt has none")
        if verifier.request.source_trial_request_digest != request.request_digest:
            raise ValueError("verifier receipt does not bind the trial request")
        if verifier.request.task_digest != task.task_digest:
            raise ValueError("verifier receipt does not bind the frozen task")
        if verifier.request.task_package_digest != package.package_digest:
            raise ValueError("verifier receipt does not bind the frozen task package")
        if (
            verifier.request.measurement_protocol_digest
            != request.measurement_protocol.protocol_digest
        ):
            raise ValueError("verifier receipt measurement protocol drifted")
        if verifier.measurements != receipt.measurements:
            raise ValueError(
                "trial measurements must be exactly the verifier measurements"
            )
    elif receipt.verifier_receipt is not None:
        raise ValueError(
            "trial receipt cannot attach verifier evidence when task declares none"
        )

    expected_ids = {row.measurement_id for row in plan.measurement_protocol.definitions}
    actual_ids = tuple(row.measurement_id for row in receipt.measurements)
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != expected_ids:
        raise ValueError("trial receipt does not exactly cover the measurement protocol")

    for record in receipt.measurements:
        record.validate_against(plan.measurement_protocol)
        if record.project_id != request.project_id or record.study_id != request.assignment.study_id:
            raise ValueError("trial measurement belongs to another project or study")
        if record.run_id != request.run_id:
            raise ValueError("trial measurement belongs to another run")
        if record.assignment_digest != request.assignment.assignment_digest:
            raise ValueError("trial measurement does not bind the assignment")
        if record.variant_id != request.assignment.variant_id:
            raise ValueError("trial measurement variant does not match assignment")
        if record.intervention != request.intervention:
            raise ValueError("trial measurement intervention does not match request")
        if record.revision != request.revision:
            raise ValueError("trial measurement revision does not match request")
    return receipt.measurements


class TrialVerifierOrchestrator:
    """Finalize one provider stage through the task-declared verifier boundary."""

    def finalize(
        self,
        request: TrialExecutionRequest,
        provider_receipt: TrialExecutionReceipt | TrialExecutionStageReceipt,
        *,
        verifier: TaskVerifierPort | None = None,
    ) -> TrialExecutionReceipt:
        if type(request) is not TrialExecutionRequest:
            raise TypeError("trial verifier orchestration requires TrialExecutionRequest")
        if type(provider_receipt) not in {
            TrialExecutionReceipt,
            TrialExecutionStageReceipt,
        }:
            raise TypeError(
                "trial provider must return TrialExecutionReceipt or "
                "TrialExecutionStageReceipt"
            )
        if provider_receipt.request_digest != request.request_digest:
            raise ValueError("trial provider receipt does not bind the execution request")
        if provider_receipt.assignment_digest != request.assignment.assignment_digest:
            raise ValueError("trial provider receipt does not bind the assignment")

        task = request.task
        package = None if task is None else task.package
        verifier_required = (
            package is not None and package.verifier_requirement_id is not None
        )
        if not verifier_required:
            if type(provider_receipt) is TrialExecutionReceipt:
                return provider_receipt
            if provider_receipt.verifier_artifacts:
                raise ValueError(
                    "trial without declared verifier cannot export verifier artifacts"
                )
            return TrialExecutionReceipt(
                request_digest=provider_receipt.request_digest,
                assignment_digest=provider_receipt.assignment_digest,
                measurements=provider_receipt.measurements,
                evidence_refs=provider_receipt.evidence_refs,
            )

        if type(provider_receipt) is not TrialExecutionStageReceipt:
            raise ValueError(
                "task-declared verifier requires an execution-stage receipt"
            )
        if provider_receipt.measurements:
            raise ValueError(
                "task-declared verifier forbids provider-produced final measurements"
            )
        if verifier is None:
            raise ValueError("task-declared verifier requires TaskVerifierPort")

        verifier_request = TaskVerifierRequest.for_trial(
            trial_request=request,
            artifacts=provider_receipt.verifier_artifacts,
        )
        verifier_receipt = verifier.verify(verifier_request)
        if type(verifier_receipt) is not TaskVerifierReceipt:
            raise TypeError("task verifier must return TaskVerifierReceipt")
        if verifier_receipt.request != verifier_request:
            raise ValueError("task verifier receipt does not bind the exact handoff")

        evidence_refs = tuple(
            dict.fromkeys(
                provider_receipt.evidence_refs + verifier_receipt.evidence_refs
            )
        )
        return TrialExecutionReceipt(
            request_digest=request.request_digest,
            assignment_digest=request.assignment.assignment_digest,
            measurements=verifier_receipt.measurements,
            evidence_refs=evidence_refs,
            verifier_receipt=verifier_receipt,
        )


def _artifact_json(value: ArtifactReference) -> dict[str, object]:
    if type(value) is not ArtifactReference:
        raise TypeError("measurement lineage reference must be ArtifactReference")
    return {
        "reference_id": value.reference_id,
        "scope_kind": value.scope.kind.value,
        "scope_id": value.scope.scope_id,
        "artifact_id": value.artifact_id,
        "generation": value.generation,
    }


def _artifact_from_json(value: object) -> ArtifactReference:
    if not isinstance(value, Mapping):
        raise TypeError("measurement lineage reference state must be an object")
    return ArtifactReference(
        str(value["reference_id"]),
        ScopeIdentity(ScopeKind(value["scope_kind"]), str(value["scope_id"])),
        str(value["artifact_id"]),
        int(value["generation"]),
    )


def _content_reference_json(value: MeasurementContentReference) -> dict[str, object]:
    return {
        "reference": _artifact_json(value.reference),
        "content_digest": value.content_digest,
        "schema_id": value.schema_id,
        "media_type": value.media_type,
    }


def _content_reference_from_json(value: object) -> MeasurementContentReference:
    if not isinstance(value, Mapping):
        raise TypeError("measurement content reference state must be an object")
    return MeasurementContentReference(
        _artifact_from_json(value["reference"]),
        str(value["content_digest"]),
        str(value["schema_id"]),
        str(value["media_type"]),
    )


def _measurement_value_json(value: MeasurementValue) -> dict[str, object]:
    if type(value) is not MeasurementValue:
        raise TypeError("measurement value codec requires MeasurementValue")
    carriers = {
        MeasurementValueKind.SCALAR: value.scalar,
        MeasurementValueKind.BOOLEAN: value.boolean,
        MeasurementValueKind.CATEGORICAL: value.categorical,
        MeasurementValueKind.STRUCTURED: (
            None if value.structured is None else thaw_json(value.structured)
        ),
        MeasurementValueKind.SEQUENCE: (
            None if value.sequence is None else thaw_json(value.sequence)
        ),
        MeasurementValueKind.DISTRIBUTION: value.distribution,
        MeasurementValueKind.MATRIX: value.matrix,
        MeasurementValueKind.TEXT_JUDGEMENT: value.text_judgement,
        MeasurementValueKind.CONTENT_REFERENCE: (
            None
            if value.content_reference is None
            else _content_reference_json(value.content_reference)
        ),
    }
    return {
        "kind": value.kind.value,
        "value": carriers[value.kind],
    }


def _measurement_value_from_json(value: object) -> MeasurementValue:
    if not isinstance(value, Mapping):
        raise TypeError("measurement value state must be an object")
    kind = MeasurementValueKind(value["kind"])
    payload = value.get("value")
    kwargs: dict[str, object] = {"kind": kind}
    if kind is MeasurementValueKind.SCALAR:
        kwargs["scalar"] = payload
    elif kind is MeasurementValueKind.BOOLEAN:
        kwargs["boolean"] = payload
    elif kind is MeasurementValueKind.CATEGORICAL:
        kwargs["categorical"] = payload
    elif kind is MeasurementValueKind.STRUCTURED:
        if not isinstance(payload, Mapping):
            raise TypeError("structured measurement state must be an object")
        kwargs["structured"] = dict(payload)
    elif kind is MeasurementValueKind.SEQUENCE:
        if not isinstance(payload, (tuple, list)):
            raise TypeError("sequence measurement state must be a sequence")
        kwargs["sequence"] = tuple(payload)
    elif kind is MeasurementValueKind.DISTRIBUTION:
        if not isinstance(payload, (tuple, list)):
            raise TypeError("distribution measurement state must be a sequence")
        kwargs["distribution"] = tuple(tuple(row) for row in payload)
    elif kind is MeasurementValueKind.MATRIX:
        if not isinstance(payload, (tuple, list)):
            raise TypeError("matrix measurement state must be a sequence")
        kwargs["matrix"] = tuple(tuple(row) for row in payload)
    elif kind is MeasurementValueKind.TEXT_JUDGEMENT:
        kwargs["text_judgement"] = payload
    elif kind is MeasurementValueKind.CONTENT_REFERENCE:
        kwargs["content_reference"] = _content_reference_from_json(payload)
    return MeasurementValue(**kwargs)


def _measurement_record_json(record: MeasurementRecord) -> dict[str, object]:
    if type(record) is not MeasurementRecord:
        raise TypeError("measurement record codec requires MeasurementRecord")
    return {
        "project_id": record.project_id,
        "study_id": record.study_id,
        "run_id": record.run_id,
        "assignment_digest": record.assignment_digest,
        "variant_id": record.variant_id,
        "producer_id": record.producer_id,
        "producer_revision_digest": record.producer_revision_digest,
        "measurement_id": record.measurement_id,
        "schema_id": record.schema_id,
        "measurement_semantic_digest": record.measurement_semantic_digest,
        "measurement_protocol_semantic_digest": record.measurement_protocol_semantic_digest,
        "value": _measurement_value_json(record.value),
        "logical_time": record.logical_time,
        "intervention_digest": record.intervention.digest,
        "revision_digest": record.revision.digest,
        "lineage_refs": tuple(_artifact_json(row) for row in record.lineage_refs),
        "record_digest": record.record_digest,
    }


def _measurement_record_from_json(value: object) -> MeasurementRecord:
    if not isinstance(value, Mapping):
        raise TypeError("measurement record state must be an object")
    refs = value.get("lineage_refs", ())
    if not isinstance(refs, (tuple, list)):
        raise TypeError("measurement lineage state must be a sequence")
    record = MeasurementRecord(
        project_id=str(value["project_id"]),
        study_id=str(value["study_id"]),
        run_id=str(value["run_id"]),
        assignment_digest=str(value["assignment_digest"]),
        variant_id=str(value["variant_id"]),
        producer_id=str(value["producer_id"]),
        producer_revision_digest=str(value["producer_revision_digest"]),
        measurement_id=str(value["measurement_id"]),
        schema_id=str(value["schema_id"]),
        measurement_semantic_digest=str(value["measurement_semantic_digest"]),
        measurement_protocol_semantic_digest=str(
            value["measurement_protocol_semantic_digest"]
        ),
        value=_measurement_value_from_json(value["value"]),
        logical_time=str(value["logical_time"]),
        intervention=OptionalIdentityFacet(value.get("intervention_digest")),
        revision=OptionalIdentityFacet(value.get("revision_digest")),
        lineage_refs=tuple(_artifact_from_json(row) for row in refs),
    )
    if record.record_digest != value.get("record_digest"):
        raise ValueError("measurement record state digest mismatch")
    return record


@dataclass(frozen=True, slots=True)
class CompiledTrialExperimentProgram:
    plan: CompiledResearchPlan
    program: ResearchProgram

    def initial_data(self, run_id: str) -> dict[str, object]:
        if type(run_id) is not str or not run_id.strip():
            raise ValueError("trial experiment run_id must be non-empty")
        return {
            "research_plan_digest": self.plan.research_plan_digest,
            "run_id": run_id,
            "assignment_cursor": 0,
            "measurement_records": (),
            "trial_receipt_digests": (),
        }


def compile_trial_experiment_program(
    plan: CompiledResearchPlan,
) -> CompiledTrialExperimentProgram:
    if type(plan) is not CompiledResearchPlan:
        raise TypeError("trial experiment compiler requires CompiledResearchPlan")
    assignment_digests = tuple(
        row.assignment_digest for row in plan.experiment_plan.assignments
    )
    if not assignment_digests:
        raise ValueError("trial experiment requires at least one assignment")
    program = (
        ExperimentProgramBuilder.create(
            program_id=f"trial-experiment:{plan.experiment.project_id}",
            version="1",
            state_schema="trial-experiment.program-state.v1",
            entrypoint="execute-trial",
        )
        .semantic(
            "execute-trial",
            ExperimentConcern.SCHEDULING,
            "experiment.trial.execute",
            configuration={
                "research_plan_digest": plan.research_plan_digest,
                "assignment_digests": assignment_digests,
                "trial_protocol_digest": plan.trial_protocol_identity.digest(),
                "measurement_protocol_digest": plan.measurement_protocol.protocol_digest,
            },
            next_node="execute-trial",
        )
        .build()
    )
    return CompiledTrialExperimentProgram(plan, program)


class TrialExperimentProgramBinding:
    """Machine-backed execution of a compiled trial matrix.

    The provider/verifier implement one trial operation. Assignment scheduling,
    progress, receipt identity and measurement state are owned by the
    ExperimentMachine journal.
    """

    def __init__(
        self,
        compiled: CompiledTrialExperimentProgram,
        provider: TrialProviderPort,
        *,
        verifier: TaskVerifierPort | None = None,
    ) -> None:
        if not isinstance(compiled, CompiledTrialExperimentProgram):
            raise TypeError(
                "trial experiment binding requires CompiledTrialExperimentProgram"
            )
        if not callable(getattr(provider, "run_trial", None)):
            raise TypeError("trial experiment binding requires TrialProviderPort")
        expected_protocol = compiled.plan.trial_protocol_identity
        protocol_identity = getattr(provider, "protocol_identity", None)
        if protocol_identity != expected_protocol:
            raise ValueError(
                "trial provider protocol identity does not match compiled plan"
            )
        self.compiled = compiled
        self.provider = provider
        self.verifier = verifier
        self._binding_by_variant = {
            row.variant.variant_id: row
            for row in compiled.plan.experiment_plan.bindings
        }

    def handlers(self) -> ProgramHandlerRegistry:
        registry = ProgramHandlerRegistry()

        def execute_trial(request: ProgramNodeRequest) -> ProgramNodeResult:
            plan = self.compiled.plan
            data = request.data
            if data.get("research_plan_digest") != plan.research_plan_digest:
                raise ValueError("trial ExperimentProgram research plan drift")
            run_id = data.get("run_id")
            if type(run_id) is not str or not run_id.strip():
                raise ValueError("trial ExperimentProgram run_id is invalid")
            cursor = data.get("assignment_cursor", 0)
            if type(cursor) is not int or cursor < 0:
                raise ValueError("trial ExperimentProgram cursor is invalid")
            assignments = plan.experiment_plan.assignments
            if cursor >= len(assignments):
                raise ValueError("trial ExperimentProgram cursor exceeds plan")
            assignment = assignments[cursor]
            binding = self._binding_by_variant[assignment.variant_id]
            request_value = TrialExecutionRequest(
                plan.experiment.project_id,
                run_id,
                plan.research_plan_digest,
                plan.research_semantics.revision,
                plan.research_semantics.participant_schedule,
                OptionalIdentityFacet(binding.intervention_digest),
                assignment,
                binding,
                plan.measurement_protocol,
                plan.trial_protocol_identity,
                (
                    plan.task_for(assignment.task_id)
                    if assignment.task_id is not None
                    else None
                ),
            )
            provider_receipt = self.provider.run_trial(request_value)
            receipt = TrialVerifierOrchestrator().finalize(
                request_value,
                provider_receipt,
                verifier=self.verifier,
            )
            records = _require_measurements(plan, request_value, receipt)
            existing_records = data.get("measurement_records", ())
            existing_receipts = data.get("trial_receipt_digests", ())
            if not isinstance(existing_records, (tuple, list)):
                raise TypeError("trial ExperimentProgram records must be a sequence")
            if not isinstance(existing_receipts, (tuple, list)):
                raise TypeError("trial ExperimentProgram receipts must be a sequence")
            next_cursor = cursor + 1
            completed = next_cursor == len(assignments)
            return ProgramNodeResult(
                value={
                    "assignment_digest": assignment.assignment_digest,
                    "receipt_digest": receipt.receipt_digest,
                    "measurement_record_digests": tuple(
                        row.record_digest for row in records
                    ),
                },
                state_update={
                    "assignment_cursor": next_cursor,
                    "measurement_records": tuple(existing_records)
                    + tuple(_measurement_record_json(row) for row in records),
                    "trial_receipt_digests": tuple(existing_receipts)
                    + (receipt.receipt_digest,),
                },
                status=MachineStatus.COMPLETED if completed else None,
                events=({
                    "type": "trial_assignment_completed",
                    "assignment_digest": assignment.assignment_digest,
                    "receipt_digest": receipt.receipt_digest,
                    "measurement_record_digests": tuple(
                        row.record_digest for row in records
                    ),
                },),
            )

        registry.register(
            "experiment.trial.execute",
            execute_trial,
            implementation_digest=canonical_digest({
                "operation": "experiment.trial.execute",
                "implementation_revision": 1,
            }),
        )
        return registry

    def open_session(
        self,
        *,
        run_id: str,
        journal: MachineJournalPort | None = None,
        snapshot_store: MachineSnapshotStorePort | None = None,
    ) -> ResearchMachineSession:
        if type(run_id) is not str or not run_id.strip():
            raise ValueError("trial experiment run_id must be non-empty")
        program = self.compiled.program
        plan = self.compiled.plan
        host = ResearchProgramHost(
            host_id="experiment.trial-matrix",
            program=program,
            journal=journal if journal is not None else InMemoryMachineJournal(),
            snapshot_store=snapshot_store,
            base_handlers=self.handlers(),
            dependency_identity={
                "research_plan_digest": plan.research_plan_digest,
                "trial_protocol_digest": plan.trial_protocol_identity.digest(),
                "measurement_protocol_digest": (
                    plan.measurement_protocol.protocol_digest
                ),
                "assignment_digests": tuple(
                    row.assignment_digest
                    for row in plan.experiment_plan.assignments
                ),
            },
        )
        return host.open_session(
            machine_id=(
                f"trial-experiment:{plan.experiment.project_id}:{run_id}"
            ),
            instance_identity={
                "run_id": run_id,
                "research_plan_digest": plan.research_plan_digest,
                "participant_schedule": plan.research_semantics.participant_schedule,
                "revision": plan.research_semantics.revision,
            },
            binding=None,
        )

    def execute(
        self,
        *,
        run_id: str,
        journal: MachineJournalPort | None = None,
        snapshot_store: MachineSnapshotStorePort | None = None,
    ) -> TrialMatrixExecutionReport:
        session = self.open_session(
            run_id=run_id,
            journal=journal,
            snapshot_store=snapshot_store,
        )
        if not session.started:
            session.start(
                self.compiled.initial_data(run_id),
                command_id=f"{session.machine_id}:start",
            )
        if session.status is MachineStatus.RUNNABLE:
            run = session.run_until_blocked(
                command_id_prefix=f"{session.machine_id}:drive",
                max_steps=len(self.compiled.plan.experiment_plan.assignments) + 1,
            )
            if run.status is not MachineStatus.COMPLETED:
                raise RuntimeError(
                    f"trial ExperimentProgram stopped with status={run.status.value}"
                )
        elif session.status is not MachineStatus.COMPLETED:
            raise RuntimeError(
                f"trial ExperimentProgram is not executable: {session.status.value}"
            )
        session.checkpoint()
        return trial_report_from_data(self.compiled, session.data)


def trial_report_from_data(
    compiled: CompiledTrialExperimentProgram,
    data: object,
) -> TrialMatrixExecutionReport:
    if not isinstance(data, dict):
        raise TypeError("trial ExperimentProgram data must be an object")
    plan = compiled.plan
    if data.get("research_plan_digest") != plan.research_plan_digest:
        raise ValueError("trial report state belongs to another research plan")
    run_id = data.get("run_id")
    if type(run_id) is not str or not run_id.strip():
        raise ValueError("trial report run_id is invalid")
    rows = data.get("measurement_records", ())
    receipts = data.get("trial_receipt_digests", ())
    if not isinstance(rows, (tuple, list)):
        raise TypeError("trial report measurement state must be a sequence")
    if not isinstance(receipts, (tuple, list)):
        raise TypeError("trial report receipt state must be a sequence")
    records = tuple(_measurement_record_from_json(row) for row in rows)
    expected = len(plan.experiment_plan.assignments)
    if len(receipts) != expected:
        raise ValueError("trial ExperimentProgram has not completed every assignment")
    return TrialMatrixExecutionReport(
        plan.experiment.project_id,
        run_id,
        plan.research_plan_digest,
        records,
        tuple(str(value) for value in receipts),
    )


__all__ = [
    "CompiledTrialExperimentProgram",
    "TrialExperimentProgramBinding",
    "TrialVerifierOrchestrator",
    "compile_trial_experiment_program",
    "trial_report_from_data",
]
