import json
from pathlib import Path
from importlib.resources import files

from noetrium_platform.foundation.governance.system_registry.api import SystemLayer, system_catalog
from noetrium_platform.foundation.governance.architecture.system_topology_invariants import audit_system_topology_completeness
import noetrium_platform.foundation.governance.architecture.system_topology_invariants as topology_invariants

def _components():
    return json.loads(
        (
            Path(__file__).parents[1]
            / "noetrium_platform/foundation/governance/system_registry/components.json"
        ).read_text(encoding="utf-8")
    )

def test_vnext_catalog_has_unique_keys_and_parent_first_order():
    rows=system_catalog(); keys=[row.identity.key for row in rows]
    assert len(keys)==len(set(keys))
    seen=set()
    for row in rows:
        assert row.parent_key in seen or row.parent_key is None
        seen.add(row.identity.key)

def test_topology_nodes_distinguish_direct_authority_from_other_roles():
    allowed_planes = {'api', 'runtime', 'providers', 'composition'}
    for row in system_catalog():
        assert row.package_prefix
        assert row.owns and row.must_not_own
        assert set(row.shape) <= allowed_planes
        if row.node_kind.value == 'authority':
            assert row.shape
            assert len(row.authorities) == 1
            assert row.authority_id
            assert row.canonical_authority_key == row.identity.key
        else:
            assert row.authorities == ()
            if row.canonical_authority_key is not None:
                assert row.canonical_authority_key != row.identity.key


def test_runtime_descriptor_preserves_canonical_catalog_semantics():
    catalog = json.loads(
        files('noetrium_platform.foundation.governance.system_registry').joinpath('catalog.json').read_text(encoding='utf-8')
    )
    for row in system_catalog():
        source = catalog[row.identity.key]
        expected_direct = source['authority'] if source['node_kind'] == 'authority' else None
        assert row.authority_id == expected_direct
        assert row.node_kind.value == source['node_kind']
        assert row.canonical_authority_key == source['canonical_authority']
        assert row.owns == source['owns']
        assert row.must_not_own == source['must_not_own']
        assert list(row.shape) == source['shape']
        assert list(row.requires) == source['requires']
        assert list(row.provides) == source['provides']
        assert list(row.components) == source['components']
        assert row.downstream_surface.value == source.get('downstream_surface', 'public')


def test_documentation_catalog_mirrors_packaged_catalog():
    packaged = files('noetrium_platform.foundation.governance.system_registry').joinpath('catalog.json').read_bytes()
    documented = (Path(__file__).parents[1] / 'docs' / 'architecture' / 'VNEXT_SYSTEM_CATALOG.json').read_bytes()
    assert packaged == documented

def test_catalog_top_level_layers_are_self_consistent_and_open():
    roots = tuple(row for row in system_catalog() if row.identity.is_system)
    assert roots
    assert len({row.identity.system_id for row in roots}) == len(roots)
    assert all(row.layer.value == row.identity.system_id for row in roots)
    assert SystemLayer("future-registered-root").value == "future-registered-root"

def test_shared_kernel_consumers_declare_platform_dependency_at_parent_system():
    by_key = {row.identity.key: row for row in system_catalog()}
    assert by_key["artifact"].requires == ("platform", "scope")
    assert by_key["data"].requires == ("artifact", "platform", "scope")


def test_runtime_system_dependency_closure_includes_component_dependencies():
    by_key = {row.identity.key: row for row in system_catalog()}
    assert by_key["runtime"].requires == (
        "artifact",
        "governance",
        "governance/release",
        "platform",
        "resource",
        "scope",
    )


def test_trial_study_convergence_keeps_study_as_experimentation_component():
    by_key = {row.identity.key: row for row in system_catalog()}
    components = _components()
    assert "scientific" not in by_key
    assert not any(key.startswith("scientific/") for key in by_key)
    assert "scientific" not in {layer.value for layer in SystemLayer}
    lifecycle = components["experimentation/lifecycle"]
    assert lifecycle["system"] == "experimentation"
    facets = {row["key"] for row in lifecycle.get("internal_facets", ())}
    assert "experimentation/lifecycle/study" in facets

def test_logging_is_one_bounded_context_with_internal_facets():
    keys={row.identity.key for row in system_catalog()}
    components=_components()
    internal = {
        "observability/logging/context","observability/logging/record","observability/logging/routing",
        "observability/logging/query","observability/logging/projection","observability/logging/retention",
        "observability/logging/capture",
    }
    assert keys.isdisjoint(internal)
    assert internal.isdisjoint(components)
    logging = components["observability/logging"]
    assert logging["system"] == "observability"
    facets={row["key"] for row in logging.get("internal_facets",())}
    assert {"observability/logging/context","observability/logging/record",
            "observability/logging/routing","observability/logging/query"} <= facets
    assert "logging.routing" in logging["provides"]
    assert "observability/logging/sink" in facets
    assert "observability/logging/sink" not in keys
    assert "observability/logging/storage" in keys

def test_section42_scaffold_contraction_keeps_system_owners_and_component_metadata():
    keys={row.identity.key for row in system_catalog()}
    components=_components()
    assert {"reliability","reliability/failure","resource","runtime"} <= keys
    assert "runtime/session" not in keys
    assert components["runtime/session"]["system"] == "runtime"
    assert components["reliability/recovery"]["system"] == "reliability"

def test_packaged_catalog_is_the_single_topology_declaration_authority():
    topology_source = (
        Path(__file__).parents[1]
        / "noetrium_platform"
        / "foundation"
        / "governance"
        / "system_registry"
        / "api"
        / "topology.py"
    ).read_text(encoding="utf-8")
    assert "_SYSTEM_TOPOLOGY" not in topology_source
    assert "_NODE_METADATA" not in topology_source
    assert "_apply_node_metadata" not in topology_source
    catalog = json.loads(
        files("noetrium_platform.foundation.governance.system_registry")
        .joinpath("catalog.json")
        .read_text(encoding="utf-8")
    )
    assert list(catalog) == [row.identity.key for row in system_catalog()]
    required_fields = {
        "authority", "must_not_own", "owns", "package_prefix", "parent",
        "shape", "requires", "provides", "components", "node_kind",
        "canonical_authority",
    }
    optional_fields = {"downstream_surface"}
    assert all(required_fields.issubset(source) for source in catalog.values())
    assert all(set(source) <= required_fields | optional_fields for source in catalog.values())
    assert all(source.get("downstream_surface", "public") in {"public", "metadata_only"} for source in catalog.values())


def test_standard_shaped_systems_cannot_bypass_catalog_authority():
    root = Path(__file__).parents[1]
    assert audit_system_topology_completeness(root) == []


def test_registered_package_authority_cannot_point_to_missing_source(tmp_path, monkeypatch):
    catalog = tmp_path / "noetrium_platform" / "foundation" / "governance" / "system_registry" / "catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("{}\n", encoding="utf-8")
    descriptor = next(row for row in system_catalog() if row.identity.key == "scope")
    monkeypatch.setattr(topology_invariants, "system_catalog", lambda: (descriptor,))
    rows = topology_invariants.audit_system_topology_completeness(tmp_path)
    assert len(rows) == 1
    assert rows[0].invariant == "stale_catalog_package"
    assert "noetrium_platform.foundation.scope" in rows[0].detail


def test_source_shape_never_creates_system_topology(tmp_path):
    package = tmp_path / "noetrium_platform" / "foundation" / "governance" / "rogue"
    for path in (tmp_path / "noetrium_platform", tmp_path / "noetrium_platform" / "foundation" / "governance", package):
        path.mkdir(parents=True, exist_ok=True)
        (path / "__init__.py").write_text("", encoding="utf-8")
    for plane in ("api", "runtime", "providers", "composition"):
        target = package / plane
        target.mkdir()
        (target / "__init__.py").write_text("", encoding="utf-8")
    assert audit_system_topology_completeness(tmp_path) == []


class _CatalogResource:
    def __init__(self, payload):
        self.payload = payload

    def read_text(self, *, encoding):
        return json.dumps(self.payload)


class _CatalogPackage:
    def __init__(self, payload):
        self.payload = payload

    def joinpath(self, _name):
        return _CatalogResource(self.payload)


def _load_catalog_payload(monkeypatch, payload):
    import noetrium_platform.foundation.governance.system_registry.api.topology as topology

    topology._load_catalog_semantics.cache_clear()
    monkeypatch.setattr(topology, "files", lambda _package: _CatalogPackage(payload))
    try:
        return topology._load_catalog_semantics()
    finally:
        topology._load_catalog_semantics.cache_clear()


def _packaged_catalog_payload():
    return json.loads(
        files("noetrium_platform.foundation.governance.system_registry")
        .joinpath("catalog.json")
        .read_text(encoding="utf-8")
    )


def test_catalog_metadata_fields_are_required_fail_closed(monkeypatch):
    import pytest

    payload = _packaged_catalog_payload()
    del payload["artifact"]["components"]
    with pytest.raises(RuntimeError, match="invalid packaged catalog descriptor"):
        _load_catalog_payload(monkeypatch, payload)


def test_catalog_metadata_rejects_duplicate_entries(monkeypatch):
    import pytest

    payload = _packaged_catalog_payload()
    payload["artifact"]["requires"] = ["scope", "scope"]
    with pytest.raises(RuntimeError, match="duplicate packaged catalog requires"):
        _load_catalog_payload(monkeypatch, payload)


def test_catalog_metadata_rejects_unknown_requirements(monkeypatch):
    import pytest

    payload = _packaged_catalog_payload()
    payload["artifact"]["requires"] = ["missing/system"]
    with pytest.raises(RuntimeError, match="is not registered"):
        _load_catalog_payload(monkeypatch, payload)


def test_catalog_metadata_rejects_duplicate_providers(monkeypatch):
    import pytest

    payload = _packaged_catalog_payload()
    payload["artifact"]["provides"] = ["dataset.registry"]
    with pytest.raises(RuntimeError, match="is provided by both"):
        _load_catalog_payload(monkeypatch, payload)


def test_catalog_runtime_metadata_is_closed_over_registered_nodes_and_capabilities():
    catalog = json.loads(
        files("noetrium_platform.foundation.governance.system_registry")
        .joinpath("catalog.json")
        .read_text(encoding="utf-8")
    )
    keys = set(catalog)
    provided_by: dict[str, str] = {}
    for key, source in catalog.items():
        assert set(source["requires"]) <= keys
        assert key not in source["requires"]
        for capability in source["provides"]:
            assert capability not in provided_by, (
                capability,
                provided_by.get(capability),
                key,
            )
            provided_by[capability] = key

def test_architecture_policy_facets_are_components_of_governance():
    root = Path(__file__).parents[1]
    keys = {row.identity.key for row in system_catalog()}
    components = _components()
    assert "governance/architecture" not in keys
    assert components["governance/architecture"]["system"] == "governance"
    assert not any((root / "noetrium_platform/foundation/governance/architecture/authority").rglob("*.py"))
    assert not any((root / "noetrium_platform/foundation/governance/architecture/dependency").rglob("*.py"))


def test_partial_source_shape_is_only_component_organization(tmp_path):
    package = tmp_path / "noetrium_platform" / "foundation" / "governance" / "partial"
    for path in (
        tmp_path / "noetrium_platform",
        tmp_path / "noetrium_platform" / "foundation" / "governance",
        package,
    ):
        path.mkdir(parents=True, exist_ok=True)
        (path / "__init__.py").write_text("", encoding="utf-8")
    for plane in ("api", "runtime"):
        target = package / plane
        target.mkdir()
        (target / "__init__.py").write_text("", encoding="utf-8")
    assert audit_system_topology_completeness(tmp_path) == []


def test_registered_system_missing_declared_plane_is_fail_closed(tmp_path, monkeypatch):
    catalog = tmp_path / "noetrium_platform" / "foundation" / "governance" / "system_registry" / "catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("{}\n", encoding="utf-8")
    descriptor = next(row for row in system_catalog() if row.identity.key == "scope")
    package = tmp_path.joinpath(*descriptor.package_prefix.split("."))
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    for plane in ("api", "runtime", "composition"):
        target = package / plane
        target.mkdir()
        (target / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(topology_invariants, "system_catalog", lambda: (descriptor,))
    rows = topology_invariants.audit_system_topology_completeness(tmp_path)
    assert len(rows) == 1
    assert rows[0].invariant == "incomplete_catalog_package_shape"
    assert "providers" in rows[0].detail
