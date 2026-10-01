"""Strict durable codec for non-claim operational model serving inventories."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointRoute,
    OperationalModelEndpointReplica,
    ModelEndpointReplicaSet,
    OperationalModelServingInventory,
)
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity, JsonValue


OPERATIONAL_MODEL_SERVING_INVENTORY_FILE_SCHEMA = (
    "noetrium.operational-model-serving-inventory.v1"
)


class OperationalModelServingInventoryReadError(ValueError):
    """The persisted inventory is absent, malformed, or semantically invalid."""


def _require_mapping(value: object, field: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise OperationalModelServingInventoryReadError(f"{field} must be an object")
    return value


def decode_operational_model_serving_inventory(
    document: Mapping[str, JsonValue],
) -> OperationalModelServingInventory:
    if document.get("schema") != OPERATIONAL_MODEL_SERVING_INVENTORY_FILE_SCHEMA:
        raise OperationalModelServingInventoryReadError(
            "operational inventory schema mismatch"
        )

    model_doc = _require_mapping(document.get("model"), "model")
    try:
        model = ImmutableModelIdentity(**dict(model_doc))
    except Exception as exc:
        raise OperationalModelServingInventoryReadError(
            "operational inventory model identity is invalid"
        ) from exc

    served_model_name = document.get("served_model_name")
    if not isinstance(served_model_name, str) or not served_model_name.strip():
        raise OperationalModelServingInventoryReadError(
            "operational inventory served_model_name is required"
        )

    raw_replicas = document.get("replicas")
    if not isinstance(raw_replicas, list) or not raw_replicas:
        raise OperationalModelServingInventoryReadError(
            "operational inventory requires non-empty replicas"
        )

    replicas: list[OperationalModelEndpointReplica] = []
    for index, raw in enumerate(raw_replicas):
        row = _require_mapping(raw, f"replicas[{index}]")
        capacity = row.get("capacity")
        if type(capacity) is not int or capacity <= 0:
            raise OperationalModelServingInventoryReadError(
                f"replicas[{index}].capacity must be positive"
            )
        try:
            route = ModelEndpointRoute(
                deployment_id=str(row["deployment_id"]),
                deployment_generation=str(row["deployment_generation"]),
                base_url=str(row["base_url"]),
                completion_path=str(
                    row.get("completion_path", "/v1/chat/completions")
                ),
                timeout_s=float(row.get("timeout_s", 120.0)),
            )
            replicas.append(OperationalModelEndpointReplica(route, capacity))
        except (KeyError, TypeError, ValueError) as exc:
            raise OperationalModelServingInventoryReadError(
                f"replicas[{index}] is invalid"
            ) from exc

    try:
        return OperationalModelServingInventory(
            model=model,
            served_model_name=served_model_name,
            replica_set=ModelEndpointReplicaSet(tuple(replicas)),
        )
    except (TypeError, ValueError) as exc:
        raise OperationalModelServingInventoryReadError(
            "operational inventory is internally inconsistent"
        ) from exc


def load_operational_model_serving_inventory(
    path: str | Path,
) -> OperationalModelServingInventory:
    source = Path(path).expanduser().resolve(strict=False)
    if not source.is_file():
        raise OperationalModelServingInventoryReadError(
            f"operational inventory is missing: {source}"
        )
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperationalModelServingInventoryReadError(
            f"operational inventory cannot be decoded: {source}"
        ) from exc
    if not isinstance(document, Mapping):
        raise OperationalModelServingInventoryReadError(
            "operational inventory root must be an object"
        )
    return decode_operational_model_serving_inventory(document)


__all__ = [
    "OPERATIONAL_MODEL_SERVING_INVENTORY_FILE_SCHEMA",
    "OperationalModelServingInventoryReadError",
    "decode_operational_model_serving_inventory",
    "load_operational_model_serving_inventory",
]
