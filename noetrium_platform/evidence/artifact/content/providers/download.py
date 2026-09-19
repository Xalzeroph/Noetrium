from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen

from noetrium_platform.evidence.artifact.catalog.api import ArtifactRecord
from noetrium_platform.evidence.artifact.content.api.acquisition import (
    ArtifactAcquisitionError,
    ArtifactHttpOpener,
    ArtifactHttpResponse,
    ArtifactAcquisitionPort,
    ArtifactAcquisitionRequest,
    ArtifactAcquisitionResult,
)
from ._publication import (
    PublicationLock,
    PublicationLockBusy,
    PublicationLockUnavailable,
    fsync_directory,
)


HttpOpener = ArtifactHttpOpener


def _default_opener(request: Request, timeout_s: float) -> ArtifactHttpResponse:
    return urlopen(request, timeout=timeout_s)  # type: ignore[return-value]


def _digests(path: Path) -> tuple[str, str, int]:
    sha256 = hashlib.sha256()
    sha1 = hashlib.sha1()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            sha256.update(block)
            sha1.update(block)
            size += len(block)
    return sha256.hexdigest(), sha1.hexdigest(), size


def _cleanup_temporary(path: Path | None, *, primary: BaseException) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except Exception as cleanup_exc:
        if isinstance(primary, Exception):
            raise ArtifactAcquisitionError(
                "TEMP_CLEANUP_FAILED",
                f"failed to remove temporary artifact {path}: "
                f"{type(cleanup_exc).__name__}: {cleanup_exc}",
            ) from primary
        primary.add_note(
            f"temporary artifact cleanup failed for {path}: "
            f"{type(cleanup_exc).__name__}: {cleanup_exc}"
        )


def _close_response(response: ArtifactHttpResponse, *, primary: BaseException | None) -> None:
    try:
        response.close()
    except BaseException as close_exc:
        if primary is None:
            raise
        primary.add_note(
            "artifact HTTP response close failed: "
            f"{type(close_exc).__name__}"
        )


class HttpArtifactAcquirer(ArtifactAcquisitionPort):
    """Streaming HTTP artifact provider with atomic publication and digest proof."""

    def __init__(self, *, opener: HttpOpener | None = None, user_agent: str = "noetrium-artifact/1") -> None:
        if not user_agent.strip():
            raise ValueError("artifact user agent must be non-empty")
        self._opener = opener or _default_opener
        self._user_agent = user_agent

    def acquire(self, request: ArtifactAcquisitionRequest) -> ArtifactAcquisitionResult:
        destination = Path(request.destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        guard = destination.with_name(f".{destination.name}.acquire.lock")
        try:
            with PublicationLock(guard):
                return self._acquire_owned(request, destination)
        except PublicationLockBusy as exc:
            raise ArtifactAcquisitionError(
                "PUBLICATION_BUSY",
                f"another acquisition owns the destination transaction: {destination}",
            ) from exc
        except PublicationLockUnavailable as exc:
            raise ArtifactAcquisitionError(
                "PUBLICATION_LOCK_UNAVAILABLE",
                f"artifact acquisition lock is unavailable: {destination}",
            ) from exc

    def _acquire_owned(
        self,
        request: ArtifactAcquisitionRequest,
        destination: Path,
    ) -> ArtifactAcquisitionResult:
        if destination.exists():
            existing = self._verify_existing(destination, request)
            if existing is not None:
                return existing
            if not request.replace_existing:
                raise ArtifactAcquisitionError(
                    "EXISTING_ARTIFACT_MISMATCH",
                    f"existing artifact does not match expected digest: {destination}",
                )

        temporary_path: Path | None = None
        try:
            fd, raw_path = tempfile.mkstemp(
                prefix=f".{destination.name}.", dir=str(destination.parent)
            )
            temporary_path = Path(raw_path)
            sha256_hasher = hashlib.sha256()
            sha1_hasher = hashlib.sha1()
            size = 0
            with os.fdopen(fd, "wb") as output:
                response = self._opener(
                    Request(request.source_url, headers={"User-Agent": self._user_agent}),
                    request.timeout_s,
                )
                response_failure: BaseException | None = None
                try:
                    status = int(getattr(response, "status", 200))
                    if status >= 400:
                        raise ArtifactAcquisitionError("HTTP_STATUS", f"HTTP status {status}")
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        output.write(block)
                        sha256_hasher.update(block)
                        sha1_hasher.update(block)
                        size += len(block)
                except BaseException as exc:
                    response_failure = exc
                    raise
                finally:
                    _close_response(response, primary=response_failure)
                output.flush()
                os.fsync(output.fileno())

            sha256 = sha256_hasher.hexdigest()
            sha1 = sha1_hasher.hexdigest()
            self._verify_digests(request, sha256, sha1, size)
            temporary_path.replace(destination)
            fsync_directory(destination.parent)
            temporary_path = None
            return ArtifactAcquisitionResult(
                record=self._record(request, sha256),
                storage_provider_id="artifact.filesystem",
                location=str(destination),
                downloaded=True,
                sha256=sha256,
                sha1=sha1,
                size=size,
            )
        except ArtifactAcquisitionError as exc:
            _cleanup_temporary(temporary_path, primary=exc)
            raise
        except Exception as exc:
            failure = ArtifactAcquisitionError(
                "DOWNLOAD_FAILED",
                f"{type(exc).__name__}: {exc}",
            )
            _cleanup_temporary(temporary_path, primary=failure)
            raise failure from exc
        except BaseException as exc:
            _cleanup_temporary(temporary_path, primary=exc)
            raise

    @staticmethod
    def _verify_existing(
        path: Path,
        request: ArtifactAcquisitionRequest,
    ) -> ArtifactAcquisitionResult | None:
        sha256, sha1, size = _digests(path)
        try:
            HttpArtifactAcquirer._verify_digests(request, sha256, sha1, size)
        except ArtifactAcquisitionError:
            return None
        return ArtifactAcquisitionResult(
            record=HttpArtifactAcquirer._record(request, sha256),
            storage_provider_id="artifact.filesystem",
            location=str(path),
            downloaded=False,
            sha256=sha256,
            sha1=sha1,
            size=size,
        )

    @staticmethod
    def _verify_digests(request: ArtifactAcquisitionRequest, sha256: str, sha1: str, size: int) -> None:
        if request.expected_sha256 is not None and sha256.lower() != request.expected_sha256.lower():
            raise ArtifactAcquisitionError(
                "SHA256_MISMATCH",
                f"expected {request.expected_sha256}, got {sha256}",
            )
        if request.expected_sha1 is not None and sha1.lower() != request.expected_sha1.lower():
            raise ArtifactAcquisitionError(
                "SHA1_MISMATCH",
                f"expected {request.expected_sha1}, got {sha1}",
            )
        if request.expected_size is not None and size != request.expected_size:
            raise ArtifactAcquisitionError(
                "SIZE_MISMATCH",
                f"expected {request.expected_size}, got {size}",
            )

    @staticmethod
    def _record(request: ArtifactAcquisitionRequest, sha256: str) -> ArtifactRecord:
        return ArtifactRecord(
            artifact_id=request.artifact_id,
            kind=request.kind,
            scope=request.scope,
            digest=sha256,
            producer_component_id=request.producer_component_id,
            producer_operation_id=request.producer_operation_id,
            media_type=request.media_type,
            retention=request.retention,
            metadata=(
                ("source_url", request.source_url),
                *( (("expected_sha1", request.expected_sha1),) if request.expected_sha1 else () ),
                *( (("expected_sha256", request.expected_sha256),) if request.expected_sha256 else () ),
            ),
        )


__all__ = ["ArtifactHttpResponse", "HttpArtifactAcquirer", "HttpOpener"]
