from pathlib import Path
from types import SimpleNamespace

import noetrium_platform.composition.environment_capability_runtime as runtime
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE


class _Registry:
    def __init__(self):
        self.rows = []

    def put(self, row):
        self.rows.append(row)
        return row


def test_runtime_materializes_official_server_asset_before_lifetime_authority(
    tmp_path: Path, monkeypatch
):
    calls = []
    record = SimpleNamespace(digest="a" * 64)

    class Provider:
        def acquire(self, version, *, destination, scope, producer_operation_id):
            calls.append((version, destination, scope, producer_operation_id))
            Path(destination).write_bytes(b"official-server")
            return SimpleNamespace(record=record)

    acquisition = SimpleNamespace(acquirer=object())
    monkeypatch.setattr(runtime, "compose_artifact_acquisition", lambda: acquisition)
    monkeypatch.setattr(
        runtime,
        "compose_official_minecraft_server_artifacts",
        lambda **kwargs: SimpleNamespace(provider=Provider()),
    )
    registry = _Registry()
    context = SimpleNamespace(content=SimpleNamespace(artifacts=registry))
    destination = runtime._materialize_minecraft_server_asset(
        context=context,
        program=SimpleNamespace(program_id="program"),
        definition=SimpleNamespace(definition_digest="b" * 64),
        version="1.21.1",
        asset_root=tmp_path / "minecraft-1.21.1" / "assets",
    )

    assert destination.read_bytes() == b"official-server"
    assert registry.rows == [record]
    assert calls[0][0] == "1.21.1"
    assert calls[0][1] == str(destination)
    assert calls[0][2] == PLATFORM_SCOPE
    assert len(calls[0][3]) == 64


def test_runtime_server_asset_binding_uses_digest_verified_official_provider():
    text = Path(runtime.__file__).read_text(encoding="utf-8")
    assert "compose_official_minecraft_server_artifacts" in text
    assert "compose_artifact_acquisition" in text
    assert "content.artifacts.put(result.record)" in text
