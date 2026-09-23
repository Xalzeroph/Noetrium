from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_unified_api_is_the_only_root_product_entrypoint() -> None:
    assert not (ROOT / "noetrium/platform.py").exists()
    assert not (ROOT / "noetrium_platform/platform.py").exists()

    from noetrium import api
    from noetrium_platform.product import api as product_api

    assert api.__all__ == product_api.__all__
    for name in api.__all__:
        assert getattr(api, name) is getattr(product_api, name)


def test_host_route_provider_is_constructed_at_one_authority() -> None:
    source = (
        ROOT / "noetrium_platform/infrastructure/lifecycle/host/composition/authorities.py"
    ).read_text(encoding="utf-8")
    assert source.count("LocalOperatingSystemRoute()") == 1
    assert "operating_system = local_operating_system_route()" in source
