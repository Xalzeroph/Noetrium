from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlencode, urlparse
from urllib.request import Request, urlopen

from noetrium_platform.evidence.artifact.content.api import ArtifactHttpOpener, ArtifactHttpResponse
from noetrium_platform.infrastructure.lifecycle.toolchain.api import (
    JavaRuntimeProvisioningRequest,
    RuntimeToolchainError,
)

_METADATA_HOST = "api.adoptium.net"
_DOWNLOAD_HOST = "github.com"
_DOWNLOAD_PATH = re.compile(r"^/adoptium/temurin\d+-binaries/releases/download/")
_MAX_METADATA_BYTES = 4 * 1024 * 1024

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class TemurinDownloadInfo:
    feature_version: int
    semantic_version: str
    release_name: str
    metadata_url: str
    source_url: str
    archive_name: str
    sha256: str
    size: int


class TemurinMetadataResolverPort(Protocol):
    def resolve(self, request: JavaRuntimeProvisioningRequest) -> TemurinDownloadInfo: ...


def _default_metadata_opener(
    request: Request, timeout_s: float
) -> ArtifactHttpResponse:
    return urlopen(request, timeout=timeout_s)  # type: ignore[return-value]


def metadata_url(request: JavaRuntimeProvisioningRequest) -> str:
    query = urlencode(
        {
            "architecture": request.platform.architecture,
            "image_type": "jdk",
            "os": request.platform.operating_system,
            "vendor": "eclipse",
        }
    )
    return (
        f"https://{_METADATA_HOST}/v3/assets/latest/"
        f"{request.feature_version}/hotspot?{query}"
    )


def validate_official_download_url(value: str, feature_version: int) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _DOWNLOAD_HOST
        or _DOWNLOAD_PATH.match(parsed.path) is None
        or not parsed.path.startswith(
            f"/adoptium/temurin{feature_version}-binaries/releases/download/"
        )
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise RuntimeToolchainError(
            "UNTRUSTED_DOWNLOAD_URL",
            f"Temurin package URL is not an official Adoptium release asset: {value}",
        )
    return value


def _parse_download_info(
    payload: JsonValue,
    request: JavaRuntimeProvisioningRequest,
    resolved_metadata_url: str,
) -> TemurinDownloadInfo:
    # JSON is untrusted only inside this boundary parser. No Mapping/dict-shaped
    # contract escapes it; successful parsing returns the typed value object.
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise RuntimeToolchainError(
            "METADATA_SHAPE_INVALID",
            "Temurin latest-assets response must contain exactly one release object",
        )
    asset = payload[0]
    binary = asset.get("binary")
    version_data = asset.get("version")
    package = binary.get("package") if isinstance(binary, dict) else None
    if not isinstance(binary, dict) or not isinstance(version_data, dict) or not isinstance(package, dict):
        raise RuntimeToolchainError(
            "METADATA_SHAPE_INVALID",
            "Temurin release metadata has no binary, version, or package object",
        )
    if asset.get("vendor") != "eclipse":
        raise RuntimeToolchainError(
            "METADATA_IDENTITY_MISMATCH",
            f"Temurin asset vendor={asset.get('vendor')!r}; expected 'eclipse'",
        )
    expected_fields = {
        "architecture": request.platform.architecture,
        "image_type": "jdk",
        "jvm_impl": "hotspot",
        "os": request.platform.operating_system,
    }
    for name, expected in expected_fields.items():
        if binary.get(name) != expected:
            raise RuntimeToolchainError(
                "METADATA_IDENTITY_MISMATCH",
                f"Temurin binary {name}={binary.get(name)!r}; expected {expected!r}",
            )

    semantic_version = str(version_data.get("semver", "")).strip()
    declared_major = version_data.get("major")
    if declared_major is not None:
        try:
            if int(declared_major) != request.feature_version:
                raise RuntimeToolchainError(
                    "RELEASE_IDENTITY_MISMATCH",
                    f"Temurin declared major {declared_major!r} does not match feature {request.feature_version}",
                )
        except (TypeError, ValueError) as exc:
            raise RuntimeToolchainError(
                "RELEASE_IDENTITY_INVALID",
                "Temurin declared major version is invalid",
            ) from exc
    release_name = str(asset.get("release_name", "")).strip()
    if (
        not semantic_version
        or not release_name
        or len(semantic_version) > 128
        or len(release_name) > 256
    ):
        raise RuntimeToolchainError(
            "RELEASE_IDENTITY_INVALID",
            "Temurin release identity is missing or unbounded",
        )
    try:
        semantic_major = int(semantic_version.split(".", 1)[0])
    except ValueError as exc:
        raise RuntimeToolchainError(
            "RELEASE_IDENTITY_INVALID", "Temurin semantic version is invalid"
        ) from exc
    if semantic_major != request.feature_version:
        raise RuntimeToolchainError(
            "RELEASE_IDENTITY_MISMATCH",
            f"Temurin semantic version {semantic_version} does not match feature {request.feature_version}",
        )

    archive_name = str(package.get("name", "")).strip()
    source_url = validate_official_download_url(
        str(package.get("link", "")).strip(), request.feature_version
    )
    checksum = str(package.get("checksum", "")).lower().strip()
    try:
        size = int(package["size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeToolchainError(
            "PACKAGE_SIZE_INVALID", "Temurin package size is invalid"
        ) from exc
    if (
        not archive_name
        or archive_name != Path(archive_name).name
        or not archive_name.endswith(".tar.gz")
        or len(archive_name) > 255
    ):
        raise RuntimeToolchainError(
            "PACKAGE_NAME_INVALID",
            "Temurin package name must be a bounded tar.gz basename",
        )
    if unquote(Path(urlparse(source_url).path).name) != archive_name:
        raise RuntimeToolchainError(
            "PACKAGE_IDENTITY_MISMATCH",
            "Temurin package name does not match the official release asset URL",
        )
    if len(checksum) != 64 or any(
        character not in "0123456789abcdef" for character in checksum
    ):
        raise RuntimeToolchainError(
            "PACKAGE_CHECKSUM_INVALID", "Temurin package SHA-256 is invalid"
        )
    if size <= 0:
        raise RuntimeToolchainError(
            "PACKAGE_SIZE_INVALID", "Temurin package size must be positive"
        )
    return TemurinDownloadInfo(
        request.feature_version,
        semantic_version,
        release_name,
        resolved_metadata_url,
        source_url,
        archive_name,
        checksum,
        size,
    )


class AdoptiumMetadataResolver(TemurinMetadataResolverPort):
    """Fetch and validate one exact Temurin release identity from Adoptium v3."""

    def __init__(
        self,
        *,
        opener: ArtifactHttpOpener | None = None,
        user_agent: str = "noetrium-java-toolchain/1",
    ) -> None:
        if not user_agent.strip():
            raise ValueError("Java runtime user agent must be non-empty")
        self._opener = opener or _default_metadata_opener
        self._user_agent = user_agent

    def resolve(self, request: JavaRuntimeProvisioningRequest) -> TemurinDownloadInfo:
        resolved_metadata_url = metadata_url(request)
        try:
            response = self._opener(
                Request(
                    resolved_metadata_url,
                    headers={"User-Agent": self._user_agent},
                ),
                min(request.timeout_s, 30.0),
            )
            try:
                status = int(getattr(response, "status", 200))
                if status >= 400:
                    raise RuntimeToolchainError(
                        "METADATA_HTTP_STATUS",
                        f"HTTP status {status} from {resolved_metadata_url}",
                    )
                raw = response.read(_MAX_METADATA_BYTES + 1)
                if len(raw) > _MAX_METADATA_BYTES:
                    raise RuntimeToolchainError(
                        "METADATA_SIZE_LIMIT",
                        f"Temurin metadata exceeds {_MAX_METADATA_BYTES} bytes",
                    )
                payload = json.loads(raw.decode("utf-8"))
            finally:
                response.close()
        except RuntimeToolchainError:
            raise
        except Exception as exc:
            raise RuntimeToolchainError(
                "METADATA_FETCH_FAILED",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        return _parse_download_info(payload, request, resolved_metadata_url)


__all__ = [
    "AdoptiumMetadataResolver",
    "TemurinDownloadInfo",
    "TemurinMetadataResolverPort",
    "metadata_url",
    "validate_official_download_url",
]
