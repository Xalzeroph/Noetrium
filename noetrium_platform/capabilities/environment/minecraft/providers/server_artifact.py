from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from typing import Any, Mapping

from noetrium_platform.evidence.artifact.catalog.api import ArtifactKind, ArtifactRecord, ArtifactRetention
from noetrium_platform.evidence.artifact.content.api import (
    ArtifactAcquisitionPort,
    ArtifactAcquisitionRequest,
    ArtifactAcquisitionResult,
    ArtifactHttpOpener,
    ArtifactHttpResponse,
)
from noetrium_platform.foundation.scope.api import ScopeIdentity


VERSION_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
_OFFICIAL_HOSTS = frozenset({"piston-meta.mojang.com", "piston-data.mojang.com", "launcher.mojang.com"})


@dataclass(frozen=True, slots=True)
class MinecraftServerDownloadInfo:
    version: str
    url: str
    sha1: str
    size: int | None = None
    release_type: str | None = None


class MinecraftServerArtifactError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"Minecraft server artifact failed [{code}]: {message}")
        self.code = code


def _official_url(url: str, *, role: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _OFFICIAL_HOSTS:
        raise MinecraftServerArtifactError("UNTRUSTED_OFFICIAL_URL", f"{role} URL is not an official HTTPS Mojang URL: {url}")
    return url


def _read_json(opener: ArtifactHttpOpener, url: str, *, timeout_s: float, user_agent: str) -> Mapping[str, Any]:
    try:
        response: ArtifactHttpResponse = opener(
            Request(_official_url(url, role="metadata"), headers={"User-Agent": user_agent}),
            timeout_s,
        )
        try:
            status = int(getattr(response, "status", 200))
            if status >= 400:
                raise MinecraftServerArtifactError("METADATA_HTTP_STATUS", f"HTTP status {status} from {url}")
            value = json.loads(response.read().decode("utf-8"))
        finally:
            response.close()
    except MinecraftServerArtifactError:
        raise
    except Exception as exc:
        raise MinecraftServerArtifactError("METADATA_FETCH_FAILED", f"{type(exc).__name__}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise MinecraftServerArtifactError("METADATA_SHAPE_INVALID", f"expected JSON object from {url}")
    return value


class OfficialMinecraftServerArtifactProvider:
    """Minecraft-specific manifest adapter over the generic artifact acquirer."""

    def __init__(
        self,
        acquirer: ArtifactAcquisitionPort,
        *,
        metadata_opener: ArtifactHttpOpener | None = None,
        user_agent: str = "noetrium-minecraft-artifact/1",
    ) -> None:
        if not user_agent.strip():
            raise ValueError("Minecraft artifact user agent must be non-empty")
        self._acquirer = acquirer
        self._metadata_opener = metadata_opener or (
            lambda request, timeout_s: urlopen(request, timeout=timeout_s)  # type: ignore[return-value]
        )
        self._user_agent = user_agent

    def resolve(self, version: str, *, timeout_s: float = 30.0) -> MinecraftServerDownloadInfo:
        if not version.strip():
            raise ValueError("Minecraft server version must be non-empty")
        manifest = _read_json(self._metadata_opener, VERSION_MANIFEST_URL, timeout_s=timeout_s, user_agent=self._user_agent)
        versions = manifest.get("versions")
        if not isinstance(versions, list):
            raise MinecraftServerArtifactError("MANIFEST_SHAPE_INVALID", "Mojang version manifest has no versions list")
        metadata = next((item for item in versions if isinstance(item, Mapping) and item.get("id") == version), None)
        if not isinstance(metadata, Mapping) or not metadata.get("url"):
            raise MinecraftServerArtifactError("VERSION_NOT_FOUND", f"Minecraft version not found: {version}")
        detail = _read_json(self._metadata_opener, str(metadata["url"]), timeout_s=timeout_s, user_agent=self._user_agent)
        downloads = detail.get("downloads")
        server = downloads.get("server") if isinstance(downloads, Mapping) else None
        if not isinstance(server, Mapping) or not server.get("url") or not server.get("sha1"):
            raise MinecraftServerArtifactError("SERVER_DOWNLOAD_MISSING", f"official metadata has no server download for {version}")
        source_url = _official_url(str(server["url"]), role="server")
        sha1 = str(server["sha1"]).lower()
        if len(sha1) != 40 or any(c not in "0123456789abcdef" for c in sha1):
            raise MinecraftServerArtifactError("SERVER_SHA1_INVALID", f"invalid server SHA-1 for {version}")
        raw_size = server.get("size")
        size = int(raw_size) if raw_size is not None else None
        if size is not None and size < 0:
            raise MinecraftServerArtifactError("SERVER_SIZE_INVALID", f"invalid server size for {version}")
        return MinecraftServerDownloadInfo(version, source_url, sha1, size, str(metadata.get("type")) if metadata.get("type") else None)

    def acquire(
        self,
        version: str,
        *,
        destination: str,
        scope: ScopeIdentity,
        producer_operation_id: str | None = None,
        timeout_s: float = 120.0,
        replace_existing: bool = False,
    ) -> ArtifactAcquisitionResult:
        info = self.resolve(version, timeout_s=min(timeout_s, 30.0))
        result = self._acquirer.acquire(
            ArtifactAcquisitionRequest(
                artifact_id=f"minecraft.server.{info.version}",
                source_url=info.url,
                destination=destination,
                scope=scope,
                kind=ArtifactKind.RUNTIME,
                producer_component_id="environment.minecraft.server-artifact",
                producer_operation_id=producer_operation_id,
                media_type="application/java-archive",
                retention=ArtifactRetention.PROJECT,
                expected_sha1=info.sha1,
                expected_size=info.size,
                replace_existing=replace_existing,
                timeout_s=timeout_s,
            )
        )
        return result


__all__ = [
    "MinecraftServerArtifactError",
    "MinecraftServerDownloadInfo",
    "OfficialMinecraftServerArtifactProvider",
    "VERSION_MANIFEST_URL",
]
