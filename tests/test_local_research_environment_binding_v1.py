from __future__ import annotations

from noetrium_platform.composition.local_research_execution_authority import (
    _program_environment_requirement_kind,
)
from noetrium_platform.foundation.kernel.structure import symbol_unit


def _environment():
    return symbol_unit(
        "environment.minecraft",
        traits=("research.environment",),
        parameters={
            "category_id": "minecraft",
            "capabilities": ("environment.act",),
        },
    )


def test_environment_action_capability_is_generic_program_environment_binding():
    assert (
        _program_environment_requirement_kind(_environment(), "environment.act")
        == "action-capability"
    )


def test_exact_environment_definition_id_is_bindable():
    assert (
        _program_environment_requirement_kind(
            _environment(), "environment.minecraft"
        )
        == "environment-definition"
    )


def test_specialized_environment_definition_does_not_prefix_match():
    assert (
        _program_environment_requirement_kind(
            _environment(), "environment.minecraft.voyager-paper-release"
        )
        is None
    )


def test_action_requirement_still_classifies_when_environment_is_missing():
    assert (
        _program_environment_requirement_kind(None, "environment.act")
        == "action-capability"
    )
