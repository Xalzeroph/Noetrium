from pathlib import Path

from scripts.validate_agent_reproduction_scope import load_and_validate


ROOT = Path(__file__).resolve().parents[1]


def test_all_agent_discovery_scope_is_structurally_valid() -> None:
    findings, report = load_and_validate(ROOT)
    assert findings == ()
    assert report["valid"] is True
    assert report["required_domain_count"] >= 20
    assert report["seed_lineage_count"] >= 50


def test_existing_reproduction_program_is_inside_discovery_scope() -> None:
    findings, report = load_and_validate(ROOT)
    assert not [item for item in findings if item.code == "PROGRAM_METHOD_OUTSIDE_DISCOVERY_SCOPE"]
    assert report["promoted_reproduction_count"] >= 12
