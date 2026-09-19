from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

from .evidence import RELEASE_EVIDENCE_FILENAME, ReleaseEvidence, load_release_evidence, write_release_evidence
from .manifest_io import load_release_manifest, write_release_manifest
from noetrium_platform.foundation.governance.release.api import ReleaseManifest


RELEASE_AUTHORITY_FILENAME = "RELEASE_AUTHORITY.json"
RELEASE_AUTHORITY_SCHEMA_VERSION = 1


class ReleaseAuthorityMismatch(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReleaseAuthorityReceipt:
    schema_version: int
    manifest_sha256: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != RELEASE_AUTHORITY_SCHEMA_VERSION:
            raise ValueError("unsupported release authority schema")
        if len(self.manifest_sha256) != 64 or len(self.evidence_sha256) != 64:
            raise ValueError("release authority digests must be SHA-256")

    def digest(self) -> str:
        return hashlib.sha256(self.to_json_bytes(compact=True)).hexdigest()

    def to_json_bytes(self, *, compact: bool = False) -> bytes:
        if compact:
            return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return json.dumps(asdict(self), sort_keys=True, indent=2).encode("utf-8") + b"\n"


def build_release_authority_receipt(manifest: ReleaseManifest, evidence: ReleaseEvidence) -> ReleaseAuthorityReceipt:
    return ReleaseAuthorityReceipt(
        schema_version=RELEASE_AUTHORITY_SCHEMA_VERSION,
        manifest_sha256=manifest.digest(),
        evidence_sha256=evidence.digest(),
    )


def decode_release_authority_receipt(raw: bytes) -> ReleaseAuthorityReceipt:
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("release authority receipt must be an object")
        return ReleaseAuthorityReceipt(**payload)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ReleaseAuthorityMismatch("release authority receipt violates its schema") from exc


def load_release_authority_receipt(path: Path) -> ReleaseAuthorityReceipt:
    try:
        return decode_release_authority_receipt(Path(path).read_bytes())
    except OSError as exc:
        raise ReleaseAuthorityMismatch("release authority receipt is missing") from exc


def publish_release_authority(root: Path, manifest: ReleaseManifest, evidence: ReleaseEvidence) -> ReleaseAuthorityReceipt:
    """Crash-consistent two-document publication with a final commit receipt.

    Filesystem rename cannot atomically replace two independent files.  The
    receipt is therefore the commit point: readers accept the pair only when the
    final receipt binds both current documents.  A crash after either document
    replacement but before receipt publication fails closed instead of exposing a
    mixed authority pair as valid.
    """

    root = Path(root)
    if evidence.release_manifest_digest != manifest.digest():
        raise ReleaseAuthorityMismatch("release evidence does not bind release manifest")
    write_release_manifest(root / "RELEASE_MANIFEST.json", manifest)
    write_release_evidence(root / RELEASE_EVIDENCE_FILENAME, evidence)
    receipt = build_release_authority_receipt(manifest, evidence)
    atomic_replace_bytes(root / RELEASE_AUTHORITY_FILENAME, receipt.to_json_bytes())
    return receipt


def load_verified_release_authority(root: Path) -> tuple[ReleaseManifest, ReleaseEvidence, ReleaseAuthorityReceipt]:
    root = Path(root)
    receipt = load_release_authority_receipt(root / RELEASE_AUTHORITY_FILENAME)
    manifest = load_release_manifest(root / "RELEASE_MANIFEST.json")
    evidence = load_release_evidence(root / RELEASE_EVIDENCE_FILENAME)
    expected = build_release_authority_receipt(manifest, evidence)
    errors: list[str] = []
    if receipt.manifest_sha256 != expected.manifest_sha256:
        errors.append("release authority manifest digest mismatch")
    if receipt.evidence_sha256 != expected.evidence_sha256:
        errors.append("release authority evidence digest mismatch")
    if errors:
        raise ReleaseAuthorityMismatch("; ".join(errors))
    return manifest, evidence, receipt


__all__ = [
    "RELEASE_AUTHORITY_FILENAME",
    "RELEASE_AUTHORITY_SCHEMA_VERSION",
    "ReleaseAuthorityMismatch",
    "ReleaseAuthorityReceipt",
    "build_release_authority_receipt",
    "decode_release_authority_receipt",
    "load_release_authority_receipt",
    "load_verified_release_authority",
    "publish_release_authority",
]
