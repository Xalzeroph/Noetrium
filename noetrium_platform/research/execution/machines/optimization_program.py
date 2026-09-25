"""Scientific OptimizationMachine preset.

This is an ask/tell-style optimization state machine, not governance evolution.
It journals candidate identity, observations, generation, budget and selection.
Proposal/search algorithms remain replaceable Program handlers.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import math

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineKind,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_digest,
    freeze_json,
    thaw_json,
)
from .domains import OptimizationConcern
from .program_host import ResearchProgramHost
from .program import (
    ProgramHandlerRegistry,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchProgram,
)
from .rule_program import (
    ProgramRule,
    ProgramRuleSet,
    RuleDispatchMode,
    UnhandledEventPolicy,
    build_rule_handlers,
    compile_rule_program,
)


class ObjectiveDirection(StrEnum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


@dataclass(frozen=True, slots=True)
class OptimizationObjective:
    name: str
    direction: ObjectiveDirection
    weight: float = 1.0

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name.strip():
            raise ValueError("optimization objective name is required")
        if not isinstance(self.direction, ObjectiveDirection):
            raise TypeError("optimization objective direction is invalid")
        if (
            isinstance(self.weight, bool)
            or not isinstance(self.weight, (int, float))
            or not math.isfinite(float(self.weight))
            or float(self.weight) <= 0
        ):
            raise ValueError("optimization objective weight must be finite and positive")

    def as_payload(self) -> JsonObject:
        return {
            "name": self.name,
            "direction": self.direction.value,
            "weight": float(self.weight),
        }


@dataclass(frozen=True, slots=True)
class OptimizationPresetSpec:
    objectives: tuple[OptimizationObjective, ...]
    max_evaluations: int
    max_generations: int | None = None
    spec_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.objectives) is not tuple or not self.objectives:
            raise ValueError("optimization preset requires at least one objective")
        if any(not isinstance(row, OptimizationObjective) for row in self.objectives):
            raise TypeError("optimization objectives must contain OptimizationObjective")
        names = tuple(row.name for row in self.objectives)
        if len(names) != len(set(names)):
            raise ValueError("optimization objective names must be unique")
        if type(self.max_evaluations) is not int or self.max_evaluations < 1:
            raise ValueError("optimization max_evaluations must be positive")
        if self.max_generations is not None and (
            type(self.max_generations) is not int or self.max_generations < 1
        ):
            raise ValueError("optimization max_generations must be positive when provided")
        object.__setattr__(self, "spec_digest", canonical_digest({
            "objectives": tuple(row.as_payload() for row in self.objectives),
            "max_evaluations": self.max_evaluations,
            "max_generations": self.max_generations,
        }))


def optimization_rule_set() -> ProgramRuleSet:
    return ProgramRuleSet(
        (
            ProgramRule(
                "register-candidate",
                "optimization.candidate.register",
                "optimization.default.register",
                priority=100,
                semantic=OptimizationConcern.PROPOSAL.value,
            ),
            ProgramRule(
                "observe-candidate",
                "optimization.candidate.observe",
                "optimization.default.observe",
                priority=100,
                semantic=OptimizationConcern.EVALUATION.value,
            ),
            ProgramRule(
                "select",
                "optimization.select",
                "optimization.default.select",
                priority=100,
                semantic=OptimizationConcern.SELECTION.value,
            ),
            ProgramRule(
                "advance-generation",
                "optimization.generation.advance",
                "optimization.default.advance-generation",
                priority=100,
                semantic=OptimizationConcern.GENERATION.value,
            ),
            ProgramRule(
                "finalize",
                "optimization.finalize",
                "optimization.default.finalize",
                priority=100,
                semantic=OptimizationConcern.TERMINATION.value,
            ),
        ),
        mode=RuleDispatchMode.FIRST,
        unhandled=UnhandledEventPolicy.ERROR,
    )


def compile_optimization_program(
    *,
    program_id: str = "optimization.ask-tell.default",
    version: str = "1",
) -> ResearchProgram:
    return compile_rule_program(
        program_id=program_id,
        kind=MachineKind.OPTIMIZATION,
        version=version,
        state_schema="optimization.ask-tell.state.v1",
        rules=optimization_rule_set(),
    )


def optimization_initial_data(
    optimization_id: str,
    spec: OptimizationPresetSpec,
) -> JsonObject:
    if type(optimization_id) is not str or not optimization_id.strip():
        raise ValueError("optimization_id is required")
    if not isinstance(spec, OptimizationPresetSpec):
        raise TypeError("optimization initial data requires OptimizationPresetSpec")
    return {
        "optimization_id": optimization_id,
        "preset_digest": spec.spec_digest,
        "objectives": tuple(row.as_payload() for row in spec.objectives),
        "max_evaluations": spec.max_evaluations,
        "max_generations": spec.max_generations,
        "generation": 0,
        "evaluated_count": 0,
        "candidates": {},
        "incumbent_id": None,
        "selection_digest": None,
    }


def _payload(request: ProgramNodeRequest) -> dict[str, JsonValue]:
    value = thaw_json(request.payload)
    if not isinstance(value, dict):
        raise TypeError("optimization event payload must be an object")
    return value


def _data(request: ProgramNodeRequest) -> dict[str, JsonValue]:
    value = thaw_json(request.data)
    if not isinstance(value, dict):
        raise TypeError("optimization program data must be an object")
    return value


def _candidate_payload(
    *,
    candidate_id: str,
    generation: int,
    definition: JsonValue,
    parent_ids: tuple[str, ...],
    artifact_refs: tuple[str, ...],
) -> JsonObject:
    return {
        "candidate_id": candidate_id,
        "generation": generation,
        "definition": freeze_json(definition),
        "definition_digest": canonical_digest(definition),
        "parent_ids": parent_ids,
        "artifact_refs": artifact_refs,
        "metrics": (),
        "evaluated": False,
    }


def _objectives(data: dict[str, JsonValue]) -> tuple[OptimizationObjective, ...]:
    value = data.get("objectives")
    if not isinstance(value, (tuple, list)):
        raise TypeError("optimization objectives state must be a sequence")
    rows: list[OptimizationObjective] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise TypeError("optimization objective state row must be an object")
        rows.append(OptimizationObjective(
            str(row["name"]),
            ObjectiveDirection(str(row["direction"])),
            float(row["weight"]),
        ))
    return tuple(rows)


def _rank_key(
    metrics: Mapping[str, float],
    objectives: tuple[OptimizationObjective, ...],
) -> tuple[float, ...]:
    return tuple(
        (
            -float(metrics[row.name]) * float(row.weight)
            if row.direction is ObjectiveDirection.MAXIMIZE
            else float(metrics[row.name]) * float(row.weight)
        )
        for row in objectives
    )


def optimization_operations() -> ProgramHandlerRegistry:
    operations = ProgramHandlerRegistry()

    def register(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        candidate_id = payload.get("candidate_id")
        if type(candidate_id) is not str or not candidate_id.strip():
            raise ValueError("optimization candidate_id is required")
        definition = payload.get("definition")
        parent_ids_value = payload.get("parent_ids", ())
        artifact_refs_value = payload.get("artifact_refs", ())
        if isinstance(parent_ids_value, str) or not isinstance(parent_ids_value, (tuple, list)):
            raise TypeError("optimization parent_ids must be a sequence")
        if isinstance(artifact_refs_value, str) or not isinstance(artifact_refs_value, (tuple, list)):
            raise TypeError("optimization artifact_refs must be a sequence")
        parent_ids = tuple(str(value) for value in parent_ids_value)
        artifact_refs = tuple(str(value) for value in artifact_refs_value)
        if any(not value.strip() for value in (*parent_ids, *artifact_refs)):
            raise ValueError("optimization candidate references must be non-empty")
        if len(parent_ids) != len(set(parent_ids)):
            raise ValueError("optimization parent_ids must be unique")
        if len(artifact_refs) != len(set(artifact_refs)):
            raise ValueError("optimization artifact_refs must be unique")
        generation = data.get("generation", 0)
        if type(generation) is not int or generation < 0:
            raise ValueError("optimization generation is invalid")

        candidates_value = data.get("candidates", {})
        if not isinstance(candidates_value, Mapping):
            raise TypeError("optimization candidates state must be an object")
        candidates = dict(candidates_value)
        unknown_parents = tuple(value for value in parent_ids if value not in candidates)
        if unknown_parents:
            raise ValueError(f"optimization candidate has unknown parents: {unknown_parents}")
        row = _candidate_payload(
            candidate_id=candidate_id,
            generation=generation,
            definition=definition,
            parent_ids=parent_ids,
            artifact_refs=artifact_refs,
        )
        existing = candidates.get(candidate_id)
        if existing is not None and canonical_digest(existing) != canonical_digest(row):
            raise ValueError("optimization candidate identity was reused with drift")
        candidates[candidate_id] = row
        return ProgramNodeResult(
            value={
                "candidate_id": candidate_id,
                "definition_digest": row["definition_digest"],
                "generation": generation,
            },
            state_update={"candidates": candidates},
            events=({
                "type": "optimization_candidate_registered",
                "candidate_id": candidate_id,
                "generation": generation,
                "definition_digest": row["definition_digest"],
            },),
            artifact_refs=artifact_refs,
        )

    def observe(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        candidate_id = payload.get("candidate_id")
        metrics_value = payload.get("metrics")
        if type(candidate_id) is not str or not candidate_id.strip():
            raise ValueError("optimization observation candidate_id is required")
        if not isinstance(metrics_value, Mapping):
            raise TypeError("optimization observation metrics must be an object")
        objectives = _objectives(data)
        objective_names = tuple(row.name for row in objectives)
        if set(metrics_value) != set(objective_names):
            raise ValueError("optimization observation metric schema mismatch")
        metrics: dict[str, float] = {}
        for name in objective_names:
            value = metrics_value[name]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError(f"optimization metric must be finite numeric: {name}")
            metrics[name] = float(value)

        candidates_value = data.get("candidates", {})
        if not isinstance(candidates_value, Mapping):
            raise TypeError("optimization candidates state must be an object")
        candidates = dict(candidates_value)
        current = candidates.get(candidate_id)
        if not isinstance(current, Mapping):
            raise KeyError(candidate_id)
        row = dict(current)
        existing_metrics = row.get("metrics", ())
        evaluated = row.get("evaluated") is True
        metric_rows = tuple((name, metrics[name]) for name in objective_names)
        if evaluated and tuple(existing_metrics) != metric_rows:
            raise ValueError("optimization candidate observation was reused with drift")
        if evaluated:
            return ProgramNodeResult(
                value={"candidate_id": candidate_id, "metrics": metric_rows, "replayed": True}
            )

        row["metrics"] = metric_rows
        row["evaluated"] = True
        candidates[candidate_id] = row
        evaluated_count = data.get("evaluated_count", 0)
        max_evaluations = data.get("max_evaluations")
        if type(evaluated_count) is not int or evaluated_count < 0:
            raise ValueError("optimization evaluated_count is invalid")
        if type(max_evaluations) is not int or max_evaluations < 1:
            raise ValueError("optimization max_evaluations is invalid")
        if evaluated_count >= max_evaluations:
            raise ValueError("optimization evaluation budget is exhausted")
        evaluated_count += 1
        return ProgramNodeResult(
            value={
                "candidate_id": candidate_id,
                "metrics": metric_rows,
                "replayed": False,
                "evaluated_count": evaluated_count,
                "budget_remaining": max_evaluations - evaluated_count,
            },
            state_update={
                "candidates": candidates,
                "evaluated_count": evaluated_count,
            },
            events=({
                "type": "optimization_candidate_observed",
                "candidate_id": candidate_id,
                "metrics": metric_rows,
                "evaluated_count": evaluated_count,
            },),
        )

    def select(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        objectives = _objectives(data)
        candidates_value = data.get("candidates", {})
        if not isinstance(candidates_value, Mapping):
            raise TypeError("optimization candidates state must be an object")
        ranked: list[tuple[tuple[float, ...], str]] = []
        for candidate_id, value in candidates_value.items():
            if type(candidate_id) is not str or not isinstance(value, Mapping):
                raise TypeError("optimization candidate state is malformed")
            if value.get("evaluated") is not True:
                continue
            metric_rows = value.get("metrics")
            if not isinstance(metric_rows, (tuple, list)):
                raise TypeError("optimization candidate metrics state is malformed")
            metrics = {str(row[0]): float(row[1]) for row in metric_rows}
            ranked.append((_rank_key(metrics, objectives), candidate_id))
        if not ranked:
            raise ValueError("optimization selection requires evaluated candidates")
        ranked.sort(key=lambda row: (row[0], row[1]))
        incumbent_id = ranked[0][1]
        ranking = tuple(row[1] for row in ranked)
        selection_digest = canonical_digest({
            "generation": data.get("generation"),
            "objectives": tuple(row.as_payload() for row in objectives),
            "ranking": ranking,
        })
        return ProgramNodeResult(
            value={
                "incumbent_id": incumbent_id,
                "ranking": ranking,
                "selection_digest": selection_digest,
            },
            state_update={
                "incumbent_id": incumbent_id,
                "selection_digest": selection_digest,
            },
            events=({
                "type": "optimization_selection_updated",
                "incumbent_id": incumbent_id,
                "selection_digest": selection_digest,
            },),
        )

    def advance_generation(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        generation = data.get("generation", 0)
        max_generations = data.get("max_generations")
        if type(generation) is not int or generation < 0:
            raise ValueError("optimization generation is invalid")
        if max_generations is not None and (
            type(max_generations) is not int or max_generations < 1
        ):
            raise ValueError("optimization max_generations is invalid")
        next_generation = generation + 1
        if max_generations is not None and next_generation >= max_generations:
            raise ValueError("optimization generation budget is exhausted")
        return ProgramNodeResult(
            value={"generation": next_generation},
            state_update={"generation": next_generation},
            events=({
                "type": "optimization_generation_advanced",
                "generation": next_generation,
            },),
        )

    def finalize(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        incumbent_id = data.get("incumbent_id")
        if type(incumbent_id) is not str or not incumbent_id.strip():
            raise ValueError("optimization finalize requires selected incumbent")
        result_digest = canonical_digest({
            "optimization_id": data.get("optimization_id"),
            "preset_digest": data.get("preset_digest"),
            "generation": data.get("generation"),
            "evaluated_count": data.get("evaluated_count"),
            "incumbent_id": incumbent_id,
            "selection_digest": data.get("selection_digest"),
        })
        return ProgramNodeResult(
            value={
                "incumbent_id": incumbent_id,
                "result_digest": result_digest,
                "evaluated_count": data.get("evaluated_count"),
                "generation": data.get("generation"),
            },
            state_update={"result_digest": result_digest},
            status=MachineStatus.COMPLETED,
            events=({
                "type": "optimization_finalized",
                "incumbent_id": incumbent_id,
                "result_digest": result_digest,
            },),
        )

    operations.register(
        "optimization.default.register",
        register,
        implementation_digest=canonical_digest({
            "operation": "optimization.default.register",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "optimization.default.observe",
        observe,
        implementation_digest=canonical_digest({
            "operation": "optimization.default.observe",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "optimization.default.select",
        select,
        implementation_digest=canonical_digest({
            "operation": "optimization.default.select",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "optimization.default.advance-generation",
        advance_generation,
        implementation_digest=canonical_digest({
            "operation": "optimization.default.advance-generation",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "optimization.default.finalize",
        finalize,
        implementation_digest=canonical_digest({
            "operation": "optimization.default.finalize",
            "implementation_revision": 1,
        }),
    )
    return operations


def optimization_handlers() -> ProgramHandlerRegistry:
    return build_rule_handlers(optimization_rule_set(), optimization_operations())


def default_optimization_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
    preset: OptimizationPresetSpec,
) -> ResearchProgramHost:
    """Default ask/tell OptimizationProgram host."""
    if not isinstance(preset, OptimizationPresetSpec):
        raise TypeError("optimization host preset must be OptimizationPresetSpec")
    program = compile_optimization_program()
    return ResearchProgramHost(
        host_id="optimization.default",
        program=program,
        journal=journal,
        snapshot_store=snapshot_store,
        base_handlers=optimization_handlers(),
        dependency_identity={
            "rule_set_digest": optimization_rule_set().rule_set_digest,
            "preset_digest": preset.spec_digest,
        },
    )


__all__ = [
    "ObjectiveDirection",
    "OptimizationObjective",
    "OptimizationPresetSpec",
    "compile_optimization_program",
    "default_optimization_host",
    "optimization_handlers",
    "optimization_initial_data",
    "optimization_operations",
    "optimization_rule_set",
]
