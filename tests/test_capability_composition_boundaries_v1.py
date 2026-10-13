from __future__ import annotations

from pathlib import Path
import tempfile

from noetrium_platform.foundation.governance.architecture.capability_composition_invariants import (
    audit_capability_composition_boundaries,
)


def test_current_source_keeps_composition_metadata_out_of_runtime_modules() -> None:
    root = Path(__file__).resolve().parents[1]
    assert audit_capability_composition_boundaries(root) == []


def test_capability_graph_is_architecture_policy_not_outer_platform_composition() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "noetrium_platform/foundation/governance/architecture/api/capability_composition.py").is_file()
    assert (root / "noetrium_platform/foundation/governance/architecture/runtime/capability_composition.py").is_file()
    assert not (root / "noetrium_platform/composition/capability_graph.py").exists()


def test_runtime_cannot_import_or_construct_composition_metadata() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runtime = root / "noetrium_platform" / "infrastructure" / "lifecycle" / "service" / "runtime"
        runtime.mkdir(parents=True)
        (runtime / "bad.py").write_text(
            "from noetrium_platform.foundation.governance.architecture.runtime.capability_composition import CapabilityCompositionPlanner\n",
            encoding="utf-8",
        )
        rows = audit_capability_composition_boundaries(root)
        assert {row.invariant for row in rows} == {"capability_graph_runtime_firewall"}


def test_only_host_composition_can_select_the_local_os_provider() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runtime = root / "noetrium_platform" / "infrastructure" / "lifecycle" / "service" / "runtime"
        runtime.mkdir(parents=True)
        (runtime / "bad.py").write_text(
            "from noetrium_platform.infrastructure.lifecycle.host.providers import LocalOperatingSystemRoute\n",
            encoding="utf-8",
        )
        rows = audit_capability_composition_boundaries(root)
        assert {row.invariant for row in rows} == {"host_route_composition_boundary"}
