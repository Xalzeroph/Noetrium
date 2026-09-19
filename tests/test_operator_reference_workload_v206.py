from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from noetrium_platform.api import ResearchFacade
from noetrium_platform.product.operator.reference import ReferenceResearchApplication
from noetrium_platform.product.operator.reference.application import ReferencePhase, ReferenceState
from noetrium_platform.product.operator.composition.research import main
from noetrium_platform.foundation.kernel.kernel.durability import (
    ChecksummedDocumentError,
    encode_checksummed_document,
)


def test_reference_workload_runs_full_durable_lifecycle():
    with TemporaryDirectory() as td:
        root = Path(td)
        facade = ResearchFacade(ReferenceResearchApplication(root))
        assert facade.run("reference-1").state == "running"
        assert facade.inspect("reference-1").state == "running"
        assert facade.stop("reference-1").state == "stopped"
        resumed = facade.resume("reference-1")
        assert resumed.state == "running"
        assert resumed.payload["generation"] == 2
        reconciled = facade.reconcile("reference-1")
        assert reconciled.state == "running"

        restarted = ResearchFacade(ReferenceResearchApplication(root))
        evidence = restarted.evidence("reference-1")
        assert [event["action"] for event in evidence.payload["events"]] == [
            "run",
            "stop",
            "resume",
            "reconcile",
        ]


def test_reference_workload_rejects_duplicate_run_and_corruption():
    with TemporaryDirectory() as td:
        root = Path(td)
        app = ReferenceResearchApplication(root)
        facade = ResearchFacade(app)
        facade.run("reference-2")
        with pytest.raises(ValueError, match="already exists"):
            facade.run("reference-2")

        state_path = app._path("reference-2")
        document = json.loads(state_path.read_text(encoding="utf-8"))
        document["payload"]["phase"] = "stopped"
        state_path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(ChecksummedDocumentError):
            facade.inspect("reference-2")


def test_reference_workload_is_exercisable_through_installed_cli_shape(capsys):
    with TemporaryDirectory() as td:
        root = Path(td)
        config = root / "reference.json"
        config.write_text(json.dumps({"state_root": str(root / "state")}), encoding="utf-8")
        prefix = [
            "--application",
            "noetrium_platform.product.operator.reference:build_reference_application",
            "--application-config",
            str(config),
        ]
        for command in ("run", "inspect", "stop", "resume", "reconcile", "evidence"):
            assert main([*prefix, command, "reference-3"]) == 0
            row = json.loads(capsys.readouterr().out)
            assert row["ok"] is True
            assert row["command"] == command


def _write_valid_checksum_state(app, target: str, payload: dict) -> None:
    app._path(target).write_bytes(
        encode_checksummed_document("noetrium.operator-reference.v1", payload)
    )


@pytest.mark.parametrize(
    "payload, message",
    [
        (
            {
                "target": "strict-1",
                "phase": "running",
                "generation": 1,
                "events": [
                    {"sequence": 1, "action": "run", "phase": "running", "generation": 1}
                ],
                "extra": "forbidden",
            },
            "state fields",
        ),
        (
            {
                "target": "strict-1",
                "phase": "running",
                "generation": True,
                "events": [
                    {"sequence": 1, "action": "run", "phase": "running", "generation": 1}
                ],
            },
            "positive integer",
        ),
        (
            {
                "target": "strict-1",
                "phase": "running",
                "generation": 1,
                "events": [{"junk": 1}],
            },
            "event fields",
        ),
        (
            {
                "target": "strict-1",
                "phase": "running",
                "generation": 1,
                "events": [
                    {"sequence": 2, "action": "run", "phase": "running", "generation": 1}
                ],
            },
            "sequence",
        ),
        (
            {
                "target": "strict-1",
                "phase": "running",
                "generation": 2,
                "events": [
                    {"sequence": 1, "action": "run", "phase": "running", "generation": 1},
                    {"sequence": 2, "action": "resume", "phase": "running", "generation": 2},
                ],
            },
            "resume transition",
        ),
    ],
)
def test_reference_state_rejects_semantically_malformed_checksummed_documents(payload, message):
    with TemporaryDirectory() as td:
        app = ReferenceResearchApplication(Path(td))
        _write_valid_checksum_state(app, "strict-1", payload)
        with pytest.raises(ValueError, match=message):
            app._read("strict-1")


def test_reference_writer_requires_typed_valid_state_before_persisting():
    with TemporaryDirectory() as td:
        app = ReferenceResearchApplication(Path(td))
        with pytest.raises(ValueError, match="events"):
            ReferenceState("strict-2", ReferencePhase.RUNNING, 1, ())
        with pytest.raises(TypeError, match="ReferenceState"):
            app._write("strict-2", {"target": "strict-2"})  # type: ignore[arg-type]
        assert not app._path("strict-2").exists()
