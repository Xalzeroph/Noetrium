from __future__ import annotations

import json

import pytest

from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    OperationalModelServingInventoryReadError,
    load_operational_model_serving_inventory,
)


def _document() -> dict[str, object]:
    return {
        "schema": "noetrium.operational-model-serving-inventory.v1",
        "model": {
            "logical_name": "qwen3-8b-substitute",
            "model_id": "Qwen3-8B",
            "revision": "a" * 64,
            "engine": "vllm",
            "engine_version": "0.8.5",
            "dtype": "bfloat16",
            "quantization": None,
            "context_length": 8192,
            "tokenizer_revision": "b" * 64,
        },
        "served_model_name": "qwen",
        "replicas": [
            {
                "deployment_id": "replica-0",
                "deployment_generation": "c" * 64,
                "base_url": "http://127.0.0.1:18003",
                "capacity": 20,
            }
        ],
    }


def test_operational_inventory_file_loads_one_frozen_replica(tmp_path) -> None:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(_document()), encoding="utf-8")
    inventory = load_operational_model_serving_inventory(path)
    assert inventory.served_model_name == "qwen"
    assert inventory.capacity == 20
    assert inventory.replica_set.members[0].deployment_id == "replica-0"


def test_operational_inventory_file_rejects_schema_drift(tmp_path) -> None:
    document = _document()
    document["schema"] = "wrong"
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(OperationalModelServingInventoryReadError):
        load_operational_model_serving_inventory(path)
