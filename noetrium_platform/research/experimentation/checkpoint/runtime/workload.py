from __future__ import annotations

import hashlib

from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from .capture import load_workload_checkpoint, publish_workload_checkpoint
from .workload_restore import (
    WorkloadCheckpointIdentityMismatch,
    restore_workload_checkpoint,
)

from ..api import (
    RunCheckpointIntegrityError,
    WorkloadCheckpointBindingPort,
    WorkloadCheckpointBundle,
    WorkloadCheckpointComponentRef,
    WorkloadCheckpointManifest,
    WorkloadCheckpointPayload,
    WorkloadCheckpointRestoreError,
    WorkloadCheckpointStore,
    WorkloadExecutionCut,
    WorkloadRestoreStateCertainty,
    build_workload_checkpoint_manifest,
)


class WorkloadCheckpointCoordinator:
    """Capture and recover one environment-method-workload checkpoint."""

    def __init__(self, store: WorkloadCheckpointStore) -> None:
        self._store = store

    @staticmethod
    def _require_context(context: ExecutionContext) -> tuple[str, str, str]:
        if not context.run_id.strip() or not context.study_id or not context.study_id.strip():
            raise WorkloadCheckpointIdentityMismatch(
                "workload checkpoint requires run_id and study_id in ExecutionContext"
            )
        if not context.branch_id or not context.branch_id.strip():
            raise WorkloadCheckpointIdentityMismatch(
                "workload checkpoint requires branch_id in ExecutionContext"
            )
        return context.run_id, context.study_id, context.branch_id

    def capture(
        self,
        *,
        binding: WorkloadCheckpointBindingPort,
        context: ExecutionContext,
        execution_cut: WorkloadExecutionCut,
    ) -> WorkloadCheckpointManifest:
        run_id, study_id, branch_id = self._require_context(context)
        if binding.run_id != run_id or binding.study_id != study_id or binding.branch_id != branch_id:
            raise WorkloadCheckpointIdentityMismatch("checkpoint context does not match workload binding")
        components = tuple(binding.checkpoint_components())
        ids = tuple(component.component_id for component in components)
        if not ids or len(ids) != len(set(ids)):
            raise WorkloadCheckpointIntegrityError(
                "workload checkpoint requires unique non-empty component providers"
            )
        payloads: list[WorkloadCheckpointPayload] = []
        for component in components:
            payload = component.capture()
            if not isinstance(payload, bytes):
                raise TypeError(
                    f"checkpoint component returned non-bytes payload: {component.component_id}"
                )
            ref = WorkloadCheckpointComponentRef(
                component_id=component.component_id,
                codec_id=component.codec_id,
                schema_version=component.schema_version,
                payload_sha256=hashlib.sha256(payload).hexdigest(),
                payload_size=len(payload),
            )
            payloads.append(WorkloadCheckpointPayload(ref, payload))
        manifest = build_workload_checkpoint_manifest(
            run_id=run_id,
            study_id=study_id,
            workload_id=binding.workload_id,
            branch_id=branch_id,
            source_cut_id=binding.source_cut_id,
            environment_generation=binding.environment_generation,
            method_generation=binding.method_generation,
            task_manifest_digest=binding.task_manifest_digest,
            checkpoint_compatibility_digest=binding.checkpoint_compatibility_digest,
            execution_cut=execution_cut,
            component_refs=tuple(item.ref for item in payloads),
        )
        return publish_workload_checkpoint(self._store, manifest, tuple(payloads))

    def restore(
        self,
        checkpoint_id: str,
        *,
        binding: WorkloadCheckpointBindingPort,
        context: ExecutionContext,
    ) -> WorkloadCheckpointBundle:
        run_id, study_id, branch_id = self._require_context(context)
        bundle = load_workload_checkpoint(self._store, checkpoint_id)
        restore_workload_checkpoint(
            bundle,
            binding,
            run_id=run_id,
            study_id=study_id,
            branch_id=branch_id,
        )
        return bundle



__all__ = [
    "WorkloadCheckpointCoordinator",
    "WorkloadCheckpointIdentityMismatch",
    "WorkloadCheckpointRestoreError",
    "WorkloadRestoreStateCertainty",
]
