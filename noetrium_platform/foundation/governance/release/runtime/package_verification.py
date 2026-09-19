from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import zipfile

from .evidence import RELEASE_EVIDENCE_FILENAME, decode_release_evidence
from .authority import RELEASE_AUTHORITY_FILENAME, build_release_authority_receipt, decode_release_authority_receipt
from .manifest_io import decode_release_manifest


@dataclass(frozen=True, slots=True)
class ReleasePackageVerificationReport:
    clean: bool
    manifest_digest: str | None
    evidence_digest: str | None
    source_tree_sha256: str | None
    file_count: int
    errors: tuple[str, ...]


def _safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name


def _stream_member_digest(zf: zipfile.ZipFile, name: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with zf.open(name, "r") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def verify_release_package(zip_path: Path) -> ReleasePackageVerificationReport:
    """Independently verify a frozen release ZIP using bounded memory.

    Every source member is streamed; no large archive member is materialized as a
    Python bytes object merely to compute its digest.  Metadata remains small and
    is decoded directly.
    """

    errors: list[str] = []
    manifest_digest: str | None = None
    evidence_digest: str | None = None
    source_tree_sha256: str | None = None
    file_count = 0
    try:
        with zipfile.ZipFile(Path(zip_path), "r") as zf:
            infos = zf.infolist()
            names = [info.filename for info in infos]
            name_set = set(names)
            if len(names) != len(name_set):
                errors.append("duplicate ZIP member")
            for name in names:
                if not _safe_member_name(name):
                    errors.append(f"unsafe ZIP member: {name}")
            required = {"RELEASE_MANIFEST.json", RELEASE_EVIDENCE_FILENAME, RELEASE_AUTHORITY_FILENAME}
            for name in sorted(required - name_set):
                errors.append(f"missing package metadata: {name}")
            if errors:
                return ReleasePackageVerificationReport(False, None, None, None, 0, tuple(errors))

            manifest = decode_release_manifest(zf.read("RELEASE_MANIFEST.json"))
            evidence = decode_release_evidence(zf.read(RELEASE_EVIDENCE_FILENAME))
            authority = decode_release_authority_receipt(zf.read(RELEASE_AUTHORITY_FILENAME))
            expected_authority = build_release_authority_receipt(manifest, evidence)
            if authority.manifest_sha256 != expected_authority.manifest_sha256:
                errors.append("package release authority manifest digest mismatch")
            if authority.evidence_sha256 != expected_authority.evidence_sha256:
                errors.append("package release authority evidence digest mismatch")
            manifest_digest = manifest.digest()
            evidence_digest = evidence.digest()
            source_tree_sha256 = manifest.source_tree_sha256
            file_count = len(manifest.files)

            expected_members = {row.path for row in manifest.files} | required
            for name in sorted(expected_members - name_set):
                errors.append(f"missing package file: {name}")
            for name in sorted(name_set - expected_members):
                errors.append(f"unexpected package file: {name}")

            info_by_name = {info.filename: info for info in infos}
            for row in manifest.files:
                info = info_by_name.get(row.path)
                if info is None:
                    continue
                if info.is_dir():
                    errors.append(f"package member unexpectedly directory: {row.path}")
                    continue
                if info.file_size != row.size:
                    errors.append(f"package size drift: {row.path}")
                    continue
                observed_size, observed_digest = _stream_member_digest(zf, row.path)
                if observed_size != row.size:
                    errors.append(f"package size drift: {row.path}")
                elif observed_digest != row.sha256:
                    errors.append(f"package hash drift: {row.path}")

            tree_raw = "\n".join(
                f"{row.sha256}  {row.path}  {row.size}" for row in manifest.files
            ).encode("utf-8")
            if hashlib.sha256(tree_raw).hexdigest() != manifest.source_tree_sha256:
                errors.append("package source-tree digest mismatch")
            if evidence.release_manifest_digest != manifest_digest:
                errors.append("package evidence does not bind package manifest")
            if evidence.source_tree_sha256 != manifest.source_tree_sha256:
                errors.append("package evidence source-tree digest mismatch")
            if evidence.release_file_count != len(manifest.files):
                errors.append("package evidence file-count mismatch")
            if evidence.platform_code_version != manifest.platform_code_version:
                errors.append("package evidence version mismatch")
            if evidence.python_requires != manifest.python_requires:
                errors.append("package evidence python requirement mismatch")
            if not evidence.clean:
                errors.append("package evidence is not clean")
    except (OSError, zipfile.BadZipFile, KeyError, ValueError, TypeError, RuntimeError) as exc:
        errors.append(f"package decode failed: {type(exc).__qualname__}")

    return ReleasePackageVerificationReport(
        clean=not errors,
        manifest_digest=manifest_digest,
        evidence_digest=evidence_digest,
        source_tree_sha256=source_tree_sha256,
        file_count=file_count,
        errors=tuple(errors),
    )


__all__ = ["ReleasePackageVerificationReport", "verify_release_package"]
