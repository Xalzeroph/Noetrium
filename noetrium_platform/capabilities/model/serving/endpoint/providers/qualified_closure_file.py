"""Strict durable reader for one platform-published qualified model closure."""

from collections.abc import Callable
import json
from pathlib import Path

from noetrium_platform.capabilities.model.serving.api import (
    RuntimeCanaryEvidenceStorePort,
    RuntimeQualificationEvidenceStorePort,
)

from .qualified_binding import QualifiedModelDeploymentClosure
from .qualified_closure_codec import QualifiedClosureCodecError, decode_qualified_closure


class QualifiedModelClosureReadError(ValueError):
    """The persisted closure is absent, malformed, altered, or internally inconsistent."""




def _verify_runtime_receipts(decoded, runtime_store) -> None:
    """Load and verify every exact runtime qualification receipt."""
    for deployment_id, expected_digest in decoded.runtime_qualification_receipt_digests:
        receipt = runtime_store.load(decoded.runtime_manifest_digest, deployment_id)
        if receipt.digest() != expected_digest:
            raise QualifiedModelClosureReadError(
                f"runtime qualification receipt digest drift: {deployment_id}"
            )


def _load_runtime_canaries(decoded, canary_store):
    """Load each canary named by the durable qualified closure."""
    return tuple(
        canary_store.load(decoded.runtime_manifest_digest, digest)
        for digest in decoded.runtime_canary_evidence_digests
    )


def _verify_canary_digest_set(decoded, canaries) -> None:
    observed = tuple(item.evidence_digest for item in canaries)
    expected = decoded.runtime_canary_evidence_digests
    if (
        len(set(observed)) != len(observed)
        or len(set(expected)) != len(expected)
        or set(observed) != set(expected)
    ):
        raise QualifiedModelClosureReadError("runtime canary evidence digest set drift")

def load_qualified_model_deployment_closure(
    path: str | Path,
    *,
    runtime_qualification_store_factory: Callable[
        [Path], RuntimeQualificationEvidenceStorePort
    ],
    runtime_canary_store_factory: Callable[[Path], RuntimeCanaryEvidenceStorePort],
) -> QualifiedModelDeploymentClosure:
    """Load only the strict platform-published closure schema."""

    closure_path = Path(path).expanduser().resolve(strict=False)
    if not closure_path.is_file():
        raise QualifiedModelClosureReadError(
            f"qualified model closure is missing: {closure_path}"
        )
    try:
        document = json.loads(closure_path.read_text(encoding="utf-8"))
        decoded = decode_qualified_closure(document)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, QualifiedClosureCodecError) as exc:
        raise QualifiedModelClosureReadError(
            f"qualified model closure cannot be decoded: {closure_path}"
        ) from exc

    runtime_root = (
        closure_path.parent / decoded.runtime_qualification_root
    ).resolve(strict=False)
    try:
        runtime_store = runtime_qualification_store_factory(runtime_root)
    except Exception as exc:
        raise QualifiedModelClosureReadError(
            "runtime qualification store factory failed"
        ) from exc
    if not callable(getattr(runtime_store, "load", None)) or not callable(
        getattr(runtime_store, "publish", None)
    ):
        raise QualifiedModelClosureReadError(
            "runtime qualification store factory returned an invalid port"
        )

    try:
        _verify_runtime_receipts(decoded, runtime_store)
    except QualifiedModelClosureReadError:
        raise
    except Exception as exc:
        raise QualifiedModelClosureReadError(
            "runtime qualification receipt cannot be loaded"
        ) from exc

    canary_root = (closure_path.parent / decoded.runtime_canary_root).resolve(strict=False)
    try:
        canary_store = runtime_canary_store_factory(canary_root)
        canaries = _load_runtime_canaries(decoded, canary_store)
    except Exception as exc:
        raise QualifiedModelClosureReadError("runtime canary evidence cannot be loaded") from exc
    _verify_canary_digest_set(decoded, canaries)

    return QualifiedModelDeploymentClosure(
        role_manifest=decoded.role_manifest,
        deployments=decoded.deployments,
        routes=decoded.routes,
        runtime_manifest_digest=decoded.runtime_manifest_digest,
        runtime_qualifications=runtime_store,
        runtime_qualification_receipt_digests=decoded.runtime_qualification_receipt_digests,
        runtime_canary_evidence=canaries,
    )


__all__ = [
    "QualifiedModelClosureReadError",
    "load_qualified_model_deployment_closure",
]
