from __future__ import annotations

from collections.abc import Callable
import json
import math
import os
from pathlib import Path
from threading import Lock
import time

from noetrium_platform.capabilities.model.serving.api import (
    RuntimeCanaryEvidenceStorePort,
    RuntimeQualificationEvidenceStorePort,
    ServiceHeartbeat,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    QualifiedModelClosurePublication,
    QualifiedModelClosurePublicationReceipt,
)
from noetrium_platform.foundation.kernel.kernel import canonical_bytes, canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability import InterprocessFileLock, atomic_replace_bytes

from .qualified_closure_codec import (
    QualifiedClosureCodecError,
    decode_qualified_closure,
    encode_qualified_closure,
)


_LOCAL_LOCKS_GUARD = Lock()
_LOCAL_LOCKS: dict[str, Lock] = {}


class QualifiedModelClosurePublicationError(RuntimeError):
    pass


def _local_lock(path: Path) -> Lock:
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _LOCAL_LOCKS_GUARD:
        lock = _LOCAL_LOCKS.get(key)
        if lock is None:
            lock = Lock()
            _LOCAL_LOCKS[key] = lock
        return lock


def _publication_maps(publication: QualifiedModelClosurePublication):
    deployments = {item.deployment_id: item for item in publication.deployments}
    routes = {item.deployment_id: item for item in publication.routes}
    receipts = {item.deployment_id: item for item in publication.runtime_qualification_receipts}
    if len(deployments) != len(publication.deployments):
        raise QualifiedModelClosurePublicationError("qualified closure has duplicate deployments")
    if len(routes) != len(publication.routes):
        raise QualifiedModelClosurePublicationError("qualified closure has duplicate routes")
    if len(receipts) != len(publication.runtime_qualification_receipts):
        raise QualifiedModelClosurePublicationError("qualified closure has duplicate runtime receipts")
    if set(deployments) != set(routes) or set(deployments) != set(receipts):
        raise QualifiedModelClosurePublicationError(
            "qualified closure deployments, routes, and runtime receipts must align exactly"
        )
    canaries = publication.runtime_canary_evidence
    if len({item.evidence_digest for item in canaries}) != len(canaries):
        raise QualifiedModelClosurePublicationError("qualified closure has duplicate runtime canary evidence")
    return deployments, routes, receipts, canaries


def _validate(publication: QualifiedModelClosurePublication, *, now: float) -> None:
    deployments, routes, receipts, canaries = _publication_maps(publication)
    roles_by_deployment: dict[str, set[str]] = {key: set() for key in deployments}
    for assignment in publication.role_manifest.assignments:
        if assignment.deployment_id not in deployments:
            raise QualifiedModelClosurePublicationError(
                f"qualified role references missing deployment: {assignment.role}"
            )
        roles_by_deployment[assignment.deployment_id].add(assignment.role)

    for deployment_id, deployment in deployments.items():
        route = routes[deployment_id]
        receipt = receipts[deployment_id]
        certificate_digest = deployment.certificate.digest()
        if route.deployment_generation != deployment.digest():
            raise QualifiedModelClosurePublicationError(
                f"qualified endpoint route generation drift: {deployment_id}"
            )
        if receipt.stack_digest != deployment.stack.digest():
            raise QualifiedModelClosurePublicationError(
                f"runtime qualification stack drift: {deployment_id}"
            )
        if receipt.qualification_certificate_digest != certificate_digest:
            raise QualifiedModelClosurePublicationError(
                f"runtime qualification certificate drift: {deployment_id}"
            )
        if receipt.heartbeat_qualification_digest != certificate_digest:
            raise QualifiedModelClosurePublicationError(
                f"runtime heartbeat qualification drift: {deployment_id}"
            )
        heartbeat = ServiceHeartbeat(
            receipt.deployment_id, receipt.stack_digest, receipt.process_pid,
            receipt.process_start_marker, receipt.argv_digest, True,
            receipt.heartbeat_qualification_digest, receipt.heartbeat_timestamp,
        )
        expected_evidence_ref = f"heartbeat:sha256:{canonical_digest(heartbeat)}"
        if expected_evidence_ref not in receipt.evidence_refs:
            raise QualifiedModelClosurePublicationError(
                f"runtime qualification evidence identity drift: {deployment_id}"
            )
        required_roles = roles_by_deployment[deployment_id]
        if not required_roles or not required_roles.issubset(set(receipt.qualified_roles)):
            raise QualifiedModelClosurePublicationError(
                f"runtime qualification does not cover frozen roles: {deployment_id}"
            )
        if not receipt.evidence_refs:
            raise QualifiedModelClosurePublicationError(
                f"runtime qualification has no evidence refs: {deployment_id}"
            )
        if receipt.created_at > now:
            raise QualifiedModelClosurePublicationError(
                f"runtime qualification receipt is from the future: {deployment_id}"
            )
        if receipt.valid_until < now:
            raise QualifiedModelClosurePublicationError(
                "runtime qualification receipt is stale: "
                f"{deployment_id}; valid_until={receipt.valid_until:.3f}; "
                f"now={now:.3f}; expired_by={now - receipt.valid_until:.3f}s; "
                "refresh the live qualification closure before publishing"
            )

    covered: set[tuple[str, str]] = set()
    for evidence in canaries:
        deployment = deployments.get(evidence.deployment_id)
        if deployment is None:
            raise QualifiedModelClosurePublicationError(
                f"runtime canary references missing deployment: {evidence.deployment_id}"
            )
        route = routes[evidence.deployment_id]
        receipt = receipts[evidence.deployment_id]
        if not evidence.passed:
            raise QualifiedModelClosurePublicationError(
                f"runtime canary did not pass: {evidence.deployment_id}:{evidence.role}:{evidence.canary_id}"
            )
        if evidence.deployment_generation != deployment.digest():
            raise QualifiedModelClosurePublicationError("runtime canary deployment generation drift")
        if evidence.route_digest != canonical_digest(route):
            raise QualifiedModelClosurePublicationError("runtime canary route digest drift")
        if evidence.role not in roles_by_deployment[evidence.deployment_id]:
            raise QualifiedModelClosurePublicationError("runtime canary role is not frozen for deployment")
        if (evidence.process_pid, evidence.process_start_marker, evidence.argv_digest) != (
            receipt.process_pid, receipt.process_start_marker, receipt.argv_digest
        ):
            raise QualifiedModelClosurePublicationError("runtime canary process generation drift")
        if not receipt.heartbeat_timestamp <= evidence.observed_at <= receipt.valid_until:
            raise QualifiedModelClosurePublicationError("runtime canary observation is outside receipt validity")
        if evidence.observed_at > now:
            raise QualifiedModelClosurePublicationError("runtime canary observation is from the future")
        canary_ref = f"canary:sha256:{evidence.evidence_digest}"
        if canary_ref not in receipt.evidence_refs:
            raise QualifiedModelClosurePublicationError(
                "runtime qualification receipt does not bind runtime canary evidence"
            )
        covered.add((evidence.deployment_id, evidence.role))
    required = {
        (deployment_id, role)
        for deployment_id, roles in roles_by_deployment.items()
        for role in roles
    }
    if covered != required:
        missing = sorted(required - covered)
        extra = sorted(covered - required)
        raise QualifiedModelClosurePublicationError(
            f"runtime canary coverage mismatch: missing={missing}; extra={extra}"
        )


def publish_qualified_model_deployment_closure(
    path: str | Path,
    publication: QualifiedModelClosurePublication,
    *,
    runtime_qualification_store_factory: Callable[
        [Path], RuntimeQualificationEvidenceStorePort
    ],
    runtime_canary_store_factory: Callable[[Path], RuntimeCanaryEvidenceStorePort],
    now: float | None = None,
) -> QualifiedModelClosurePublicationReceipt:
    """Publish exact runtime receipts first, then expose one immutable closure atomically."""

    closure_path = Path(path).expanduser().resolve(strict=False)
    lock_path = closure_path.with_name(closure_path.name + ".publish.lock")
    document = encode_qualified_closure(
        role_manifest=publication.role_manifest,
        deployments=publication.deployments,
        routes=publication.routes,
        runtime_manifest_digest=publication.runtime_manifest_digest,
        runtime_qualification_root=publication.runtime_qualification_root,
        runtime_qualification_receipt_digests=tuple(sorted(
            (item.deployment_id, item.digest())
            for item in publication.runtime_qualification_receipts
        )),
        runtime_canary_root=publication.runtime_canary_root,
        runtime_canary_evidence_digests=tuple(sorted(
            item.evidence_digest for item in publication.runtime_canary_evidence
        )),
    )
    try:
        decoded = decode_qualified_closure(document)
    except QualifiedClosureCodecError as exc:
        raise QualifiedModelClosurePublicationError("qualified closure publication is invalid") from exc

    current_time = time.time() if now is None else float(now)
    if not math.isfinite(current_time):
        raise QualifiedModelClosurePublicationError("qualified closure publication time must be finite")
    with _local_lock(lock_path), InterprocessFileLock(lock_path):
        _validate(publication, now=current_time)
        existing_digest: str | None = None
        if closure_path.exists():
            try:
                existing = decode_qualified_closure(
                    json.loads(closure_path.read_text(encoding="utf-8"))
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, QualifiedClosureCodecError) as exc:
                raise QualifiedModelClosurePublicationError(
                    "existing qualified closure is malformed and cannot be overwritten"
                ) from exc
            if existing.closure_digest != decoded.closure_digest:
                raise QualifiedModelClosurePublicationError(
                    "qualified closure already exists with different content"
                )
            existing_digest = existing.closure_digest
        runtime_root = (closure_path.parent / decoded.runtime_qualification_root).resolve(strict=False)
        runtime_store = runtime_qualification_store_factory(runtime_root)
        evidence_paths: list[str] = []
        for receipt in sorted(
            publication.runtime_qualification_receipts,
            key=lambda item: item.deployment_id,
        ):
            try:
                evidence_path = runtime_store.publish(
                    publication.runtime_manifest_digest,
                    receipt,
                )
                loaded = runtime_store.load(
                    publication.runtime_manifest_digest,
                    receipt.deployment_id,
                )
            except Exception as exc:
                raise QualifiedModelClosurePublicationError(
                    f"runtime qualification publication failed: {receipt.deployment_id}"
                ) from exc
            if loaded.digest() != receipt.digest():
                raise QualifiedModelClosurePublicationError(
                    f"runtime qualification readback drift: {receipt.deployment_id}"
                )
            evidence_paths.append(str(evidence_path))

        canary_root = (closure_path.parent / decoded.runtime_canary_root).resolve(strict=False)
        canary_store = runtime_canary_store_factory(canary_root)
        canary_paths: list[str] = []
        for evidence in sorted(
            publication.runtime_canary_evidence,
            key=lambda item: item.evidence_digest,
        ):
            try:
                canary_path = canary_store.publish(
                    publication.runtime_manifest_digest, evidence
                )
                loaded_canary = canary_store.load(
                    publication.runtime_manifest_digest, evidence.evidence_digest
                )
            except Exception as exc:
                raise QualifiedModelClosurePublicationError(
                    f"runtime canary publication failed: {evidence.deployment_id}:{evidence.role}"
                ) from exc
            if loaded_canary != evidence:
                raise QualifiedModelClosurePublicationError(
                    f"runtime canary readback drift: {evidence.deployment_id}:{evidence.role}"
                )
            canary_paths.append(str(canary_path))

        if existing_digest is not None:
            return QualifiedModelClosurePublicationReceipt(
                closure_path=str(closure_path),
                closure_digest=existing_digest,
                runtime_evidence_paths=tuple(evidence_paths),
                runtime_canary_evidence_paths=tuple(canary_paths),
            )

        atomic_replace_bytes(closure_path, canonical_bytes(document, indent=2))
        try:
            persisted = decode_qualified_closure(
                json.loads(closure_path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, QualifiedClosureCodecError) as exc:
            raise QualifiedModelClosurePublicationError(
                "published qualified closure failed readback validation"
            ) from exc
        if persisted.closure_digest != decoded.closure_digest:
            raise QualifiedModelClosurePublicationError(
                "published qualified closure digest changed during readback"
            )
        return QualifiedModelClosurePublicationReceipt(
            closure_path=str(closure_path),
            closure_digest=persisted.closure_digest,
            runtime_evidence_paths=tuple(evidence_paths),
            runtime_canary_evidence_paths=tuple(canary_paths),
        )


__all__ = [
    "QualifiedModelClosurePublicationError",
    "publish_qualified_model_deployment_closure",
]
