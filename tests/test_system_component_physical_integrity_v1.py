from importlib.resources import files
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_registered_component_has_a_real_package() -> None:
    raw = json.loads(
        files("noetrium_platform.foundation.governance.system_registry")
        .joinpath("components.json")
        .read_text(encoding="utf-8")
    )
    missing = []
    for key, row in raw.items():
        package = ROOT.joinpath(*row["package_prefix"].split("."))
        if not package.is_dir():
            missing.append((key, row["package_prefix"]))
    assert missing == []


def test_catalog_component_references_are_exactly_declared_components() -> None:
    catalog = json.loads(
        files("noetrium_platform.foundation.governance.system_registry")
        .joinpath("catalog.json")
        .read_text(encoding="utf-8")
    )
    components = json.loads(
        files("noetrium_platform.foundation.governance.system_registry")
        .joinpath("components.json")
        .read_text(encoding="utf-8")
    )
    referenced = {
        component
        for row in catalog.values()
        for component in row.get("components", ())
    }
    assert referenced == set(components)


def test_registered_components_are_single_bounded_context_level() -> None:
    raw = json.loads(
        files("noetrium_platform.foundation.governance.system_registry")
        .joinpath("components.json")
        .read_text(encoding="utf-8")
    )
    assert all(key.count("/") == 1 for key in raw)


def test_every_registry_node_has_a_real_package() -> None:
    catalog = json.loads(
        files("noetrium_platform.foundation.governance.system_registry")
        .joinpath("catalog.json")
        .read_text(encoding="utf-8")
    )
    missing = []
    for key, row in catalog.items():
        package = ROOT.joinpath(*row["package_prefix"].split("."))
        module = package.with_suffix(".py")
        if not package.is_dir() and not module.is_file():
            missing.append((key, row["package_prefix"]))
    assert missing == []
