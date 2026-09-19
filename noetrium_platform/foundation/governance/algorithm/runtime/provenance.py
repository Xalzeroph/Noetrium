from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import re
from typing import Callable

from noetrium_platform.foundation.governance.api import (
    RepositorySourceIndexPort,
    repository_source_scope_text_digest,
)
from noetrium_platform.foundation.governance.algorithm.api import AlgorithmSnapshot

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
_IMPLEMENTATION_PATH_PREFIXES = (
    "noetrium_platform/foundation/governance/algorithm",
    "noetrium_platform/foundation/governance/api/repository_source.py",
    "noetrium_platform/foundation/governance/providers/repository_source.py",
)


def algorithm_implementation_digest(source_index: RepositorySourceIndexPort) -> str:
    return repository_source_scope_text_digest(
        source_index,
        path_prefixes=_IMPLEMENTATION_PATH_PREFIXES,
        suffixes=(".py",),
    )


def algorithm_snapshot_semantic_digest(snapshot: AlgorithmSnapshot) -> str:
    document = asdict(snapshot)
    document.pop("generated_unix_ns", None)
    payload = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def exact_snapshot_provenance_error(snapshot: AlgorithmSnapshot, *, label: str) -> str | None:
    if snapshot.schema_version != "algorithm-snapshot.v3":
        return f"{label} schema is not algorithm-snapshot.v3"
    if snapshot.source_authority != "git":
        return f"{label} source authority is not immutable Git"
    if snapshot.source_revision is None or _GIT_SHA_RE.fullmatch(snapshot.source_revision) is None:
        return f"{label} source revision is not an exact Git SHA"
    if _SHA256_RE.fullmatch(snapshot.source_digest) is None:
        return f"{label} source digest is not canonical SHA-256"
    if _SHA256_RE.fullmatch(snapshot.analyzer_implementation_digest) is None:
        return f"{label} analyzer implementation digest is not canonical SHA-256"
    if not snapshot.analyzer_revision.strip():
        return f"{label} analyzer revision is empty"
    return None


def baseline_provenance_blocker(
    baseline: AlgorithmSnapshot,
    current: AlgorithmSnapshot,
    *,
    replay: Callable[[str], AlgorithmSnapshot] | None,
) -> str | None:
    current_error = exact_snapshot_provenance_error(current, label="current algorithm snapshot")
    if current_error is not None:
        return f"algorithm exact-source provenance unavailable: {current_error}"
    baseline_error = exact_snapshot_provenance_error(baseline, label="reviewed algorithm baseline")
    if baseline_error is not None:
        return f"algorithm baseline provenance migration required: {baseline_error}"
    if baseline.analyzer_revision != current.analyzer_revision:
        return (
            "algorithm analyzer revision migration required: "
            f"{baseline.analyzer_revision} -> {current.analyzer_revision}"
        )
    if baseline.analyzer_implementation_digest != current.analyzer_implementation_digest:
        return (
            "algorithm analyzer implementation migration required: "
            f"{baseline.analyzer_implementation_digest} -> {current.analyzer_implementation_digest}"
        )
    if replay is None:
        return "algorithm baseline provenance replay is unavailable for the immutable Git source authority"
    replayed = replay(baseline.source_revision)
    replay_error = exact_snapshot_provenance_error(replayed, label="replayed algorithm baseline")
    if replay_error is not None:
        return f"algorithm baseline replay failed provenance: {replay_error}"
    if replayed.source_revision != baseline.source_revision:
        return "algorithm baseline replay resolved a different Git revision"
    if replayed.source_digest != baseline.source_digest:
        return "algorithm baseline source digest is not reconstructible from its exact Git revision"
    if algorithm_snapshot_semantic_digest(replayed) != algorithm_snapshot_semantic_digest(baseline):
        return "algorithm baseline metrics are not reproducible from exact Git source and analyzer identity"
    return None


__all__ = [
    "algorithm_implementation_digest",
    "algorithm_snapshot_semantic_digest",
    "baseline_provenance_blocker",
    "exact_snapshot_provenance_error",
]
