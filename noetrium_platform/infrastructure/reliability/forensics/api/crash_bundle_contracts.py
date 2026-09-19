from __future__ import annotations

from dataclasses import dataclass


CRASH_BUNDLE_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class CrashBundleManifest:
    schema_version: int
    failure_id: str
    failure: dict[str, object]
    taxonomy: dict[str, object]
    fingerprints: dict[str, object]
    timeline: tuple[dict[str, object], ...]
    recent_state_writers: tuple[dict[str, object], ...]
    authoritative_chain_tails: dict[str, dict[str, object]]
    artifact_refs: tuple[str, ...]
    bundle_digest: str


@dataclass(frozen=True, slots=True)
class CrashBundleVerification:
    path: str
    valid: bool
    errors: tuple[str, ...]
    failure_id: str | None
    bundle_digest: str | None
