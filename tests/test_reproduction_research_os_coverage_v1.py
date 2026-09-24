from __future__ import annotations

import importlib
from pathlib import Path

from research.reproductions.contracts import (
    ReproductionAssetKind,
    ReproductionDefinition,
)
from research.reproductions.research_os import (
    compile_reproduction_research_program,
)


_EXPECTED_MISSING_EXECUTABLE = (
    "agent_q_surrogate",
    "exact_vwa",
    "gats",
    "lits_math500",
    "tree_search_language_model_agents",
)

_EXPECTED_MISSING_STUDY = (
    "agent_s3",
    "ai_scientist_v1",
    "ai_scientist_v2",
    "gorilla_apibench",
    "live_swe_agent",
    "mars_automated_ai_research",
    "memevolve",
    "multiagent_debate",
    "pi05_openpi",
)


def _definitions() -> tuple[ReproductionDefinition, ...]:
    root = Path(__file__).resolve().parents[1] / "research" / "reproductions"
    rows = []
    for path in sorted(root.glob("*/definition.py")):
        module = importlib.import_module(
            f"research.reproductions.{path.parent.name}.definition"
        )
        definition = getattr(module, "REPRODUCTION", None)
        if type(definition) is not ReproductionDefinition:
            raise TypeError(
                f"{path.parent.name} has no typed REPRODUCTION definition"
            )
        rows.append(definition)
    return tuple(rows)


def test_reproduction_research_os_migration_coverage_is_explicit() -> None:
    definitions = _definitions()
    assert len(definitions) == 100

    current: list[str] = []
    missing_executable: list[str] = []
    missing_study: list[str] = []

    for definition in definitions:
        kinds = {asset.kind for asset in definition.assets}
        has_study = ReproductionAssetKind.STUDY in kinds
        has_executable = bool(
            {
                ReproductionAssetKind.METHOD_PROGRAM,
                ReproductionAssetKind.RESEARCH_PROGRAM,
            }
            & kinds
        )
        if not has_study:
            missing_study.append(definition.package)
            continue
        if not has_executable:
            missing_executable.append(definition.package)
            continue
        program = compile_reproduction_research_program(definition)
        assert program.program_id == definition.identity.method_id
        current.append(definition.package)

    assert len(current) == 86
    assert tuple(sorted(missing_executable)) == _EXPECTED_MISSING_EXECUTABLE
    assert tuple(sorted(missing_study)) == _EXPECTED_MISSING_STUDY
    assert set(current).isdisjoint(missing_executable)
    assert set(current).isdisjoint(missing_study)
    assert len(current) + len(missing_executable) + len(missing_study) == 100
