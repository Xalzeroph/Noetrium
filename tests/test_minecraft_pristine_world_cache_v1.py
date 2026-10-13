from pathlib import Path

from noetrium_platform.capabilities.environment.minecraft.api import MinecraftServerSpec
from noetrium_platform.capabilities.environment.minecraft.providers.pristine_world import (
    MinecraftPristineWorldTemplateCache,
    pristine_world_template_key,
)


def _spec(root: Path, name: str, *, seed: str, port: int) -> MinecraftServerSpec:
    return MinecraftServerSpec(
        jar_path=str((root / "server.jar").resolve()),
        workdir=str((root / name).resolve()),
        java_executable="/opt/java/openjdk/bin/java",
        port=port,
        level_seed=seed,
    )


def _world(spec: MinecraftServerSpec, payload: bytes = b"region-data") -> Path:
    level = Path(spec.workdir) / spec.level_name
    (level / "region").mkdir(parents=True)
    (level / "level.dat").write_bytes(b"level")
    (level / "region" / "r.0.0.mca").write_bytes(payload)
    (level / "session.lock").write_bytes(b"volatile")
    return level


def test_same_world_provenance_clones_pristine_template_across_runtime_ports(tmp_path: Path) -> None:
    asset = "a" * 64
    cache = MinecraftPristineWorldTemplateCache(tmp_path / "cache")
    first = _spec(tmp_path, "first", seed="paired", port=25565)
    second = _spec(tmp_path, "second", seed="paired", port=25566)
    assert pristine_world_template_key(first, asset_digest=asset) == pristine_world_template_key(second, asset_digest=asset)

    reservation = cache.prepare(first, asset_digest=asset)
    assert reservation is not None
    source = _world(first)
    reservation.publish(source)
    reservation.close()

    hit = cache.prepare(second, asset_digest=asset)
    assert hit is None
    cloned = Path(second.workdir) / second.level_name
    assert (cloned / "level.dat").read_bytes() == b"level"
    assert (cloned / "region" / "r.0.0.mca").read_bytes() == b"region-data"
    assert not (cloned / "session.lock").exists()


def test_different_world_seed_never_reuses_template(tmp_path: Path) -> None:
    asset = "b" * 64
    cache = MinecraftPristineWorldTemplateCache(tmp_path / "cache")
    first = _spec(tmp_path, "first", seed="seed-a", port=25565)
    second = _spec(tmp_path, "second", seed="seed-b", port=25566)
    assert pristine_world_template_key(first, asset_digest=asset) != pristine_world_template_key(second, asset_digest=asset)

    one = cache.prepare(first, asset_digest=asset)
    assert one is not None
    one.publish(_world(first, b"a"))
    one.close()

    two = cache.prepare(second, asset_digest=asset)
    assert two is not None
    two.close()
