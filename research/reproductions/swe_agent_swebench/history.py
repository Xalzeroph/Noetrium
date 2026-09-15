from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, freeze_json

from .fidelity import SWE_AGENT_PAPER_ERA_FIDELITY


@dataclass(frozen=True, slots=True)
class SWEAgentHistoryProjection:
    """Model-view projection for SWE-agent paper-era observation elision.

    Durable trajectory records are never deleted or mutated. Only observation
    content in the model-facing projection is replaced with an omission marker,
    mirroring SWE-agent's LastNObservations behavior while preserving Research
    OS host truth.
    """

    records: tuple[JsonObject, ...]
    source_count: int
    elided_observation_count: int


def _record(row: Mapping[str, JsonValue]) -> JsonObject:
    return freeze_json(dict(row))


def project_paper_era_history(
    records: Sequence[Mapping[str, JsonValue]],
    *,
    keep_observations: int = SWE_AGENT_PAPER_ERA_FIDELITY.history_observations_kept,
) -> SWEAgentHistoryProjection:
    if type(keep_observations) is not int or keep_observations <= 0:
        raise ValueError("SWE-agent observation window must be positive")
    frozen = tuple(_record(row) for row in records)
    observation_indices = [
        index
        for index, row in enumerate(frozen)
        if row.get("message_type") == "observation" and not bool(row.get("is_demo", False))
    ]
    # The paper-era processor never elides the first instance observation.
    removable = observation_indices[1 : max(1, len(observation_indices) - keep_observations)]
    removable_set = set(removable)
    projected: list[JsonObject] = []
    for index, row in enumerate(frozen):
        if index not in removable_set:
            projected.append(row)
            continue
        tags = row.get("tags", ())
        tag_values = set(tags) if isinstance(tags, (tuple, list)) else set()
        if "keep_output" in tag_values:
            projected.append(row)
            continue
        data = dict(row)
        content = data.get("content")
        line_count = len(content.splitlines()) if isinstance(content, str) else 0
        data["content"] = f"Old environment output: ({line_count} lines omitted)"
        projected.append(freeze_json(data))
    changed = sum(1 for left, right in zip(frozen, projected) if left != right)
    return SWEAgentHistoryProjection(tuple(projected), len(frozen), changed)


__all__ = ["SWEAgentHistoryProjection", "project_paper_era_history"]
