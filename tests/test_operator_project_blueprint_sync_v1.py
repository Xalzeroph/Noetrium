from __future__ import annotations

import json
from pathlib import Path

import pytest

from noetrium_platform.composition.operator.project import (
    project_doctor,
    project_scaffold,
    project_testing,
)
from noetrium_platform.composition.operator.project.project_platform_identity import (
    InstalledPlatformIdentity,
)
from noetrium_platform.foundation.governance.architecture.repository_boundary.runtime import (
    audit_downstream_project_imports,
)
from noetrium_platform.product.operator.api import ProjectCreateRequest
from noetrium_platform.product.operator.runtime.research_cli import (
    build_research_parser,
)


_FIXED_PLATFORM = InstalledPlatformIdentity("0.1.0", "a" * 64)


def _bind_fixed_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        project_scaffold,
        "installed_platform_identity",
        lambda: _FIXED_PLATFORM,
    )
    monkeypatch.setattr(
        project_doctor,
        "installed_platform_identity",
        lambda: _FIXED_PLATFORM,
    )


def test_create_emits_blueprint_generated_topology_and_fill_slots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "paper"
    receipt = project_scaffold.create_project(
        ProjectCreateRequest("paper", "0.1.0", root)
    )

    generated = set(receipt.generated_files)
    assert "research.blueprint.json" in generated
    assert "src/paper/research.py" in generated
    assert "src/paper/slots.py" in generated
    assert len(receipt.research_blueprint_digest) == 64

    topology = (root / "src" / "paper" / "research.py").read_text(
        encoding="utf-8"
    )
    slots = (root / "src" / "paper" / "slots.py").read_text(
        encoding="utf-8"
    )
    assert "AUTO-GENERATED Research OS topology" in topology
    assert "paper__method" in slots
    assert "paper__benchmark" in slots
    assert "paper__primary_metric" in slots


def test_project_sync_regenerates_topology_without_touching_user_slots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "paper"
    project_scaffold.create_project(
        ProjectCreateRequest("paper", "0.1.0", root)
    )

    slots_path = root / "src" / "paper" / "slots.py"
    user_slots = "# USER OWNED\n" + slots_path.read_text(encoding="utf-8")
    slots_path.write_text(user_slots, encoding="utf-8")
    slots_before = slots_path.read_bytes()

    blueprint_path = root / "research.blueprint.json"
    document = json.loads(blueprint_path.read_text(encoding="utf-8"))
    program = document["programs"][0]
    program["nodes"].append(
        {
            "node_id": "table",
            "kind": "table",
            "definition_ids": [],
            "outputs": [
                {
                    "name": "table",
                    "kind": "artifact",
                }
            ],
            "config": None,
        }
    )
    program["dependencies"].append(
        {
            "upstream_node_id": "evaluate",
            "downstream_node_id": "table",
            "bindings": [],
        }
    )
    blueprint_path.write_text(
        json.dumps(document, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    before_topology = (root / "src" / "paper" / "research.py").read_bytes()
    receipt = project_scaffold.sync_project(root)
    after_topology = (root / "src" / "paper" / "research.py").read_bytes()

    assert len(receipt.research_blueprint_digest) == 64
    assert receipt.regenerated_files == (
        "src/paper/research.py",
        "tests/test_generated_project.py",
    )
    assert slots_path.read_bytes() == slots_before
    assert after_topology != before_topology
    assert b"'table'" in after_topology

    report = project_doctor.doctor_project(
        root,
        boundary_auditor=audit_downstream_project_imports,
    )
    checks = {row.check_id: row.disposition.value for row in report.checks}
    assert report.ready
    assert checks["blueprint_projection"] == "pass"

    tested = project_testing.test_project(root)
    assert tested.passed


def test_doctor_rejects_hand_edited_generated_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_fixed_platform(monkeypatch)
    root = tmp_path / "paper"
    project_scaffold.create_project(
        ProjectCreateRequest("paper", "0.1.0", root)
    )
    topology = root / "src" / "paper" / "research.py"
    topology.write_text(
        topology.read_text(encoding="utf-8") + "\n# hand edited\n",
        encoding="utf-8",
    )

    report = project_doctor.doctor_project(
        root,
        boundary_auditor=audit_downstream_project_imports,
    )
    checks = {row.check_id: row.disposition.value for row in report.checks}
    assert not report.ready
    assert checks["blueprint_projection"] == "blocked"


def test_project_cli_exposes_blueprint_create_and_sync() -> None:
    parser = build_research_parser()
    create = parser.parse_args(
        [
            "project",
            "create",
            "paper",
            "out",
            "--blueprint",
            "paper.blueprint.json",
        ]
    )
    assert create.blueprint == Path("paper.blueprint.json")

    sync = parser.parse_args(["project", "sync", "--project", "out"])
    assert sync.project_root == Path("out")
