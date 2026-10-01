from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import noetrium_platform.composition.environment_capability_runtime as runtime
from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactNotFound,
    ArtifactRecord,
    ArtifactRetention,
)
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE


class _Registry:
    def __init__(self):
        self.rows = {}

    def put(self, row):
        current = self.rows.get(row.artifact_id)
        if current is not None and current != row:
            raise AssertionError("artifact registry identity drift")
        self.rows[row.artifact_id] = row
        return row

    def get(self, artifact_id):
        try:
            return self.rows[artifact_id]
        except KeyError as exc:
            raise ArtifactNotFound(artifact_id) from exc


def _context(tmp_path: Path, registry: _Registry):
    return SimpleNamespace(
        runtime=SimpleNamespace(
            management=SimpleNamespace(
                platform_meta=SimpleNamespace(artifacts=registry),
                physical_directories=SimpleNamespace(
                    layout=SimpleNamespace(root=lambda kind: tmp_path / kind.value)
                ),
            )
        )
    )


def _record(payload: bytes) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id="minecraft.server.1.21.1",
        kind=ArtifactKind.RUNTIME,
        scope=PLATFORM_SCOPE,
        digest=sha256(payload).hexdigest(),
        producer_component_id="environment.minecraft.server-artifact",
        producer_operation_id="1" * 64,
        media_type="application/java-archive",
        retention=ArtifactRetention.PERMANENT,
    )


def test_runtime_materializes_official_server_asset_before_lifetime_authority(
    tmp_path: Path, monkeypatch
):
    calls = []
    payload = b"official-server"
    record = _record(payload)

    class Provider:
        def acquire(
            self,
            version,
            *,
            destination,
            scope,
            producer_operation_id,
            replace_existing=False,
        ):
            calls.append(
                (
                    version,
                    destination,
                    scope,
                    producer_operation_id,
                    replace_existing,
                )
            )
            Path(destination).write_bytes(payload)
            return SimpleNamespace(record=record)

    acquisition = SimpleNamespace(acquirer=object())
    monkeypatch.setattr(runtime, "compose_artifact_acquisition", lambda: acquisition)
    monkeypatch.setattr(
        runtime,
        "compose_official_minecraft_server_artifacts",
        lambda **kwargs: SimpleNamespace(provider=Provider()),
    )
    registry = _Registry()
    context = _context(tmp_path, registry)
    destination = runtime._materialize_minecraft_server_asset(
        context=context,
        version="1.21.1",
        asset_root=tmp_path / "minecraft-1.21.1" / "assets",
    )

    assert destination.read_bytes() == payload
    assert registry.get(record.artifact_id) == record
    assert calls[0][0] == "1.21.1"
    assert calls[0][1] == str(destination)
    assert calls[0][2] == PLATFORM_SCOPE
    assert len(calls[0][3]) == 64
    assert calls[0][4] is False


def test_runtime_server_asset_warm_hit_uses_platform_record_without_network(
    tmp_path: Path, monkeypatch
):
    payload = b"official-server"
    record = _record(payload)
    registry = _Registry()
    registry.put(record)
    asset_root = tmp_path / "minecraft-1.21.1" / "assets"
    asset_root.mkdir(parents=True)
    destination = asset_root / "server.jar"
    destination.write_bytes(payload)

    monkeypatch.setattr(
        runtime,
        "compose_artifact_acquisition",
        lambda: (_ for _ in ()).throw(AssertionError("warm hit must not acquire")),
    )
    monkeypatch.setattr(
        runtime,
        "compose_official_minecraft_server_artifacts",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("warm hit must not resolve Mojang metadata")
        ),
    )

    observed = runtime._materialize_minecraft_server_asset(
        context=_context(tmp_path, registry),
        version="1.21.1",
        asset_root=asset_root,
    )

    assert observed == destination
    assert observed.read_bytes() == payload


def test_runtime_server_asset_binding_uses_platform_durable_authority():
    text = Path(runtime.__file__).read_text(encoding="utf-8")
    assert "platform_meta.artifacts" in text
    assert "ContentAddressedSingleFlight" in text
    assert "sha256_file(destination)" in text
