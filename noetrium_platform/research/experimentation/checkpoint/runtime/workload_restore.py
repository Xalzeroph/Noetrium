from __future__ import annotations

from dataclasses import dataclass

from ..api import (
    WorkloadCheckpointBindingPort,
    WorkloadCheckpointBundle,
    WorkloadCheckpointComponentPort,
    WorkloadCheckpointComponentRef,
    WorkloadCheckpointPayload,
    WorkloadCheckpointRestoreError,
    WorkloadRestoreStateCertainty,
)


class WorkloadCheckpointIdentityMismatch(RuntimeError):
    """A loaded checkpoint does not match the requested workload binding."""


@dataclass(frozen=True, slots=True)
class _RestoreRow:
    component_id: str
    component: WorkloadCheckpointComponentPort
    payload: WorkloadCheckpointPayload


def _require_manifest_identity(
    bundle: WorkloadCheckpointBundle,
    binding: WorkloadCheckpointBindingPort,
    *,
    run_id: str,
    study_id: str,
    branch_id: str,
) -> None:
    manifest = bundle.manifest
    expected = {
        "run_id": run_id,
        "study_id": study_id,
        "workload_id": binding.workload_id,
        "branch_id": branch_id,
        "source_cut_id": binding.source_cut_id,
        "environment_generation": binding.environment_generation,
        "method_generation": binding.method_generation,
        "task_manifest_digest": binding.task_manifest_digest,
        "checkpoint_compatibility_digest": binding.checkpoint_compatibility_digest,
    }
    actual = {key: getattr(manifest, key) for key in expected}
    if actual != expected:
        raise WorkloadCheckpointIdentityMismatch(
            f"workload checkpoint identity mismatch: expected={expected!r} actual={actual!r}"
        )


def _component_index(
    binding: WorkloadCheckpointBindingPort,
) -> tuple[tuple[str, ...], dict[str, WorkloadCheckpointComponentPort]]:
    components: dict[str, WorkloadCheckpointComponentPort] = {}
    ids: list[str] = []
    for component in binding.checkpoint_components():
        if component.component_id in components:
            raise WorkloadCheckpointIdentityMismatch(
                "workload checkpoint binding component topology is not unique"
            )
        ids.append(component.component_id)
        components[component.component_id] = component
    if not ids:
        raise WorkloadCheckpointIdentityMismatch(
            "workload checkpoint binding component topology is empty"
        )
    return tuple(ids), components


def _payload_index(
    bundle: WorkloadCheckpointBundle,
) -> tuple[tuple[str, ...], dict[str, WorkloadCheckpointPayload]]:
    payloads: dict[str, WorkloadCheckpointPayload] = {}
    ids: list[str] = []
    for payload in bundle.payloads:
        component_id = payload.ref.component_id
        if component_id in payloads:
            raise WorkloadCheckpointIdentityMismatch(
                "workload checkpoint payload topology contains duplicates"
            )
        ids.append(component_id)
        payloads[component_id] = payload
    return tuple(ids), payloads


def _require_restore_topology(
    component_ids: tuple[str, ...],
    manifest_ids: tuple[str, ...],
    payload_ids: tuple[str, ...],
) -> None:
    expected = set(manifest_ids)
    if set(component_ids) != expected:
        raise WorkloadCheckpointIdentityMismatch("workload checkpoint component topology mismatch")
    if set(payload_ids) != expected:
        raise WorkloadCheckpointIdentityMismatch("workload checkpoint payload topology mismatch")


def _bind_restore_row(
    component_id: str,
    component: WorkloadCheckpointComponentPort,
    payload: WorkloadCheckpointPayload,
    manifest_ref: WorkloadCheckpointComponentRef,
) -> _RestoreRow:
    if payload.ref != manifest_ref:
        raise WorkloadCheckpointIdentityMismatch(
            f"workload checkpoint payload reference drift: {component_id}"
        )
    if (component.codec_id, component.schema_version) != (
        manifest_ref.codec_id,
        manifest_ref.schema_version,
    ):
        raise WorkloadCheckpointIdentityMismatch(
            f"workload checkpoint codec drift: {component_id}"
        )
    return _RestoreRow(component_id, component, payload)


def _bind_restore_rows(
    bundle: WorkloadCheckpointBundle,
    binding: WorkloadCheckpointBindingPort,
) -> tuple[_RestoreRow, ...]:
    component_ids, components = _component_index(binding)
    payload_ids, payloads = _payload_index(bundle)
    manifest_ids = tuple(item.component_id for item in bundle.manifest.component_refs)
    _require_restore_topology(component_ids, manifest_ids, payload_ids)
    manifest_refs = {item.component_id: item for item in bundle.manifest.component_refs}
    return tuple(
        _bind_restore_row(
            component_id,
            components[component_id],
            payloads[component_id],
            manifest_refs[component_id],
        )
        for component_id in manifest_ids
    )


def _capture_preimages(rows: tuple[_RestoreRow, ...]) -> dict[str, bytes]:
    preimages: dict[str, bytes] = {}
    for row in rows:
        try:
            preimage = row.component.capture()
            if type(preimage) is not bytes:
                raise TypeError("checkpoint component preimage must be bytes")
        except BaseException as exc:
            raise WorkloadCheckpointRestoreError(
                phase="preimage_capture",
                component_id=row.component_id,
                primary=exc,
                state_certainty=WorkloadRestoreStateCertainty.UNCHANGED,
            ) from exc
        preimages[row.component_id] = preimage
    return preimages


def _rollback(
    attempted: tuple[_RestoreRow, ...],
    preimages: dict[str, bytes],
) -> tuple[tuple[str, BaseException], ...]:
    errors: list[tuple[str, BaseException]] = []
    for row in reversed(attempted):
        try:
            row.component.restore(preimages[row.component_id])
        except BaseException as exc:
            errors.append((row.component_id, exc))
    return tuple(errors)


def _apply_restore(rows: tuple[_RestoreRow, ...], preimages: dict[str, bytes]) -> None:
    attempted: list[_RestoreRow] = []
    try:
        for row in rows:
            attempted.append(row)
            row.component.restore(row.payload.payload)
    except BaseException as primary:
        rollback_errors = _rollback(tuple(attempted), preimages)
        certainty = (
            WorkloadRestoreStateCertainty.UNKNOWN
            if rollback_errors
            else WorkloadRestoreStateCertainty.ROLLED_BACK
        )
        raise WorkloadCheckpointRestoreError(
            phase="apply",
            component_id=attempted[-1].component_id,
            primary=primary,
            state_certainty=certainty,
            rollback_errors=rollback_errors,
        ) from primary


def restore_workload_checkpoint(
    bundle: WorkloadCheckpointBundle,
    binding: WorkloadCheckpointBindingPort,
    *,
    run_id: str,
    study_id: str,
    branch_id: str,
) -> None:
    """Validate every restore input before mutating, then compensate on apply failure."""
    _require_manifest_identity(bundle, binding, run_id=run_id, study_id=study_id, branch_id=branch_id)
    rows = _bind_restore_rows(bundle, binding)
    preimages = _capture_preimages(rows)
    _apply_restore(rows, preimages)


__all__ = ["WorkloadCheckpointIdentityMismatch", "restore_workload_checkpoint"]
