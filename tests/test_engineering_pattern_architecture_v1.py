"""Architecture fitness: no model-local duplicate scheduling authority."""
from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.foundation.governance.architecture.engineering_pattern_invariants import (
    audit_engineering_pattern_invariants,
)
from noetrium_platform.foundation.governance.architecture.system_dependency_invariants import (
    layer_dependency_findings,
)

ROOT = Path(__file__).resolve().parents[1]


def test_model_scheduler_is_supplied_once_by_owner_composition():
    assert audit_engineering_pattern_invariants(ROOT) == []


def test_explicit_noetrium_layer_dependencies_have_no_bypasses():
    findings = layer_dependency_findings(ROOT)
    assert findings == (), [tuple((f.path, f.line, f.kind)) for f in findings]


def test_no_parallel_public_runtime_facade():
    import noetrium
    assert set(noetrium.__all__) == {"NoetriumUnit", "run"}


def test_architecture_registry_remains_single_declared_topology():
    hierarchy = json.loads((ROOT / "noetrium_platform/foundation/governance/system_registry/hierarchy.json").read_text())
    assert hierarchy["application_composition"] == "noetrium_platform.composition"
    assert "noetrium_platform.foundation.kernel.concurrency.scheduling.runtime" not in hierarchy["global_contract_prefixes"]
