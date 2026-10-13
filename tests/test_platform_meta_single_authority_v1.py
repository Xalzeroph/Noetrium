from __future__ import annotations

from noetrium_platform.composition import platform_meta


def test_platform_meta_has_one_durable_composition_entrypoint() -> None:
    assert platform_meta.__all__ == ["PlatformMetaAuthorities", "build_platform_meta"]
    assert callable(platform_meta.build_platform_meta)
    assert not hasattr(platform_meta, "build_in_memory_platform_meta")
    assert not hasattr(platform_meta, "build_durable_platform_meta")
