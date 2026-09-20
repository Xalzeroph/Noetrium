from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_unified_api_is_the_only_root_product_entrypoint() -> None:
    assert not (ROOT / "noetrium/platform.py").exists()

    from noetrium import api
    import noetrium_platform.platform as platform_owner

    for name in platform_owner.__all__:
        assert api.resolve(name) is getattr(platform_owner, name)


def test_host_route_provider_is_constructed_at_one_authority() -> None:
    source = (
        ROOT / "noetrium_platform/infrastructure/lifecycle/host/composition/authorities.py"
    ).read_text(encoding="utf-8")
    assert source.count("LocalOperatingSystemRoute()") == 1
    assert "operating_system = local_operating_system_route()" in source
