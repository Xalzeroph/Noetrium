from __future__ import annotations

import json
from pathlib import Path

import pytest

from noetrium_platform.foundation.governance.architecture.authority_disposition import (
    EXTERNAL_NON_AUTHORITATIVE,
    NODE_KINDS,
    OUTSIDE_RUNTIME_AUTHORITY_GRAPH,
    build_authority_disposition_matrix,
    validate_authority_disposition_matrix,
)
from noetrium_platform.foundation.governance.system_registry.api import system_catalog


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"
MATRIX = ROOT / "docs/architecture/AUTHORITY_DISPOSITION_MATRIX_20260916.json"


def _catalog() -> dict[str, object]:
    document = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _matrix() -> list[dict[str, object]]:
    document = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert isinstance(document, list)
    assert all(isinstance(row, dict) for row in document)
    return document


def test_checked_in_disposition_matrix_matches_live_catalog_exactly() -> None:
    catalog = _catalog()
    rows = _matrix()

    parsed = validate_authority_disposition_matrix(rows, catalog)

    assert len(parsed) == len(catalog)
    assert {row.path for row in parsed} == set(catalog)
    assert all(row.node_kind in NODE_KINDS for row in parsed)


def test_only_direct_authorities_own_themselves() -> None:
    catalog = _catalog()
    parsed = build_authority_disposition_matrix(catalog)

    for row in parsed:
        if row.node_kind == "authority":
            assert row.canonical_authority == row.path
            assert row.migration_target == row.path
        else:
            assert row.canonical_authority != row.path


def test_runtime_descriptors_never_materialize_legacy_facet_authorities() -> None:
    catalog = _catalog()
    descriptors = {descriptor.identity.key: descriptor for descriptor in system_catalog()}

    assert set(descriptors) == set(catalog)
    for path, raw in catalog.items():
        assert isinstance(raw, dict)
        descriptor = descriptors[path]
        if raw["node_kind"] == "authority":
            assert len(descriptor.authorities) == 1
            assert descriptor.authority_id == raw["authority"]
        else:
            assert descriptor.authorities == ()
            assert descriptor.authority_id is None


def test_external_provider_style_nodes_do_not_acquire_platform_authority() -> None:
    catalog = {
        "provider": {
            "node_kind": "provider",
            "canonical_authority": None,
            "owns": "provider-local implementation behavior",
            "downstream_surface": "metadata_only",
        }
    }

    (row,) = build_authority_disposition_matrix(catalog)

    assert row.canonical_authority == EXTERNAL_NON_AUTHORITATIVE
    assert row.current_authority == EXTERNAL_NON_AUTHORITATIVE
    assert row.migration_target == OUTSIDE_RUNTIME_AUTHORITY_GRAPH


def test_root_non_authority_can_be_explicitly_outside_runtime_authority_graph() -> None:
    catalog = {
        "governance": {
            "authority": "legacy_governance_policy",
            "node_kind": "facet",
            "canonical_authority": None,
            "parent": None,
            "owns": "architecture and policy surfaces",
            "downstream_surface": "public",
        }
    }

    (row,) = build_authority_disposition_matrix(catalog)

    assert row.current_authority == "legacy_governance_policy"
    assert row.canonical_authority is None
    assert row.migration_target == OUTSIDE_RUNTIME_AUTHORITY_GRAPH


def test_nested_policy_can_be_explicitly_outside_runtime_authority_graph() -> None:
    catalog = {
        "root": {
            "authority": "root_authority",
            "node_kind": "authority",
            "canonical_authority": "root",
            "parent": None,
            "owns": "root truth",
        },
        "root/gate": {
            "authority": "legacy_gate_policy",
            "node_kind": "policy",
            "canonical_authority": None,
            "parent": "root",
            "owns": "validation policy semantics",
            "downstream_surface": "metadata_only",
        },
    }

    rows = {row.path: row for row in build_authority_disposition_matrix(catalog)}
    gate = rows["root/gate"]

    assert gate.current_authority == "legacy_gate_policy"
    assert gate.canonical_authority is None
    assert gate.migration_target == OUTSIDE_RUNTIME_AUTHORITY_GRAPH


def test_cross_authority_projection_can_explicitly_stay_outside_truth_graph() -> None:
    catalog = {
        "root": {
            "authority": "root_authority",
            "node_kind": "authority",
            "canonical_authority": "root",
            "parent": None,
            "owns": "root truth",
        },
        "root/diagnostics": {
            "authority": "legacy_diagnostics_projection",
            "node_kind": "projection",
            "canonical_authority": None,
            "parent": "root",
            "owns": "derived cross-authority diagnostics",
            "downstream_surface": "metadata_only",
        },
    }

    rows = {row.path: row for row in build_authority_disposition_matrix(catalog)}
    diagnostics = rows["root/diagnostics"]

    assert diagnostics.current_authority == "legacy_diagnostics_projection"
    assert diagnostics.canonical_authority is None
    assert diagnostics.migration_target == OUTSIDE_RUNTIME_AUTHORITY_GRAPH


def test_child_facet_without_canonical_authority_fails_closed() -> None:
    catalog = {
        "root": {
            "authority": "root_authority",
            "node_kind": "authority",
            "canonical_authority": "root",
            "parent": None,
            "owns": "root truth",
        },
        "root/facet": {
            "authority": "legacy_facet_authority",
            "node_kind": "facet",
            "canonical_authority": None,
            "parent": "root",
            "owns": "ambiguous child facet",
        },
    }

    with pytest.raises(ValueError, match="must identify the authority"):
        build_authority_disposition_matrix(catalog)


def test_missing_canonical_authority_never_triggers_path_inference() -> None:
    catalog = {
        "diagnostics": {
            "authority": "legacy_diagnostics",
            "node_kind": "projection",
            "owns": "diagnostics projection",
        }
    }

    with pytest.raises(ValueError, match="canonical_authority is required"):
        build_authority_disposition_matrix(catalog)


def test_missing_node_kind_never_defaults_to_authority() -> None:
    catalog = {
        "ambiguous": {
            "authority": "ambiguous_authority",
            "canonical_authority": "ambiguous",
            "owns": "ambiguous truth",
        }
    }

    with pytest.raises(ValueError, match="node_kind is required"):
        build_authority_disposition_matrix(catalog)


def test_legacy_authority_is_preserved_as_migration_metadata_only() -> None:
    catalog = {
        "root": {
            "authority": "root_authority",
            "node_kind": "authority",
            "canonical_authority": "root",
            "parent": None,
            "owns": "root truth",
        },
        "root/facet": {
            "authority": "legacy_facet_authority",
            "node_kind": "facet",
            "canonical_authority": "root",
            "parent": "root",
            "owns": "root facet contracts",
        },
    }

    rows = {row.path: row for row in build_authority_disposition_matrix(catalog)}

    assert rows["root/facet"].current_authority == "legacy_facet_authority"
    assert rows["root/facet"].canonical_authority == "root"
    assert rows["root/facet"].migration_target == "root"


def test_authority_must_canonically_own_itself() -> None:
    catalog = {
        "a": {
            "authority": "a_authority",
            "node_kind": "authority",
            "canonical_authority": "b",
            "parent": None,
            "owns": "a truth",
        },
        "b": {
            "authority": "b_authority",
            "node_kind": "authority",
            "canonical_authority": "b",
            "parent": None,
            "owns": "b truth",
        },
    }

    with pytest.raises(ValueError, match="must canonically own itself"):
        build_authority_disposition_matrix(catalog)
