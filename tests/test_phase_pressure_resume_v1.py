from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointRoute,
    OperationalModelEndpointReplica,
    OperationalModelEndpointReplicaSet,
    OperationalModelServingInventory,
)
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity, canonical_digest
from research.runtime.phase_pressure import _load_resumable_record, discover


def _program():
    return dict(discover())["adaptagent_acl2025"]


def _inventory() -> OperationalModelServingInventory:
    return OperationalModelServingInventory(
        model=ImmutableModelIdentity(
            logical_name="qwen3-8b-substitute",
            model_id="Qwen3-8B",
            revision="a" * 64,
            engine="vllm",
            engine_version="0.8.5",
            dtype="bfloat16",
            quantization=None,
            context_length=8192,
            tokenizer_revision="b" * 64,
        ),
        served_model_name="qwen",
        replica_set=OperationalModelEndpointReplicaSet(
            (
                OperationalModelEndpointReplica(
                    ModelEndpointRoute(
                        "replica-0",
                        "c" * 64,
                        "http://127.0.0.1:18003",
                    ),
                    20,
                ),
            )
        ),
    )


def test_phase_pressure_resume_accepts_only_digest_valid_matching_result(tmp_path: Path) -> None:
    inventory = _inventory()
    out = tmp_path / "adaptagent_acl2025" / "rep-00"
    out.mkdir(parents=True)
    record = {
        "schema": "noetrium.phase-pressure-result.v2",
        "lane": "platform-pressure",
        "matched_reproduction": False,
        "claim_ready": False,
        "package": "adaptagent_acl2025",
        "repetition": 0,
        "source_sha": "d" * 40,
        "program_digest": _program().program_digest,
        "model_identity_digest": canonical_digest(inventory.model),
        "serving_inventory_digest": inventory.identity_digest,
        "replica_set_digest": inventory.replica_set.replica_set_digest,
        "status": "succeeded",
        "evidence_status": "complete",
    }
    record["record_digest"] = canonical_digest(record)
    (out / "result.json").write_text(json.dumps(record), encoding="utf-8")

    loaded = _load_resumable_record(
        output_root=tmp_path,
        package="adaptagent_acl2025",
        program=_program(),
        repetition=0,
        source_sha="d" * 40,
        inventory=inventory,
    )
    assert loaded == record

    record["status"] = "failed"
    (out / "result.json").write_text(json.dumps(record), encoding="utf-8")
    assert _load_resumable_record(
        output_root=tmp_path,
        package="adaptagent_acl2025",
        program=_program(),
        repetition=0,
        source_sha="d" * 40,
        inventory=inventory,
    ) is None
