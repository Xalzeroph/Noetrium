from __future__ import annotations

import pytest

from tests_support import ExperimentWorkflowSurfaceRegistryForTest


def test_unknown_workflow_surface_fails_without_constructing_scientific_operations():
    registry = ExperimentWorkflowSurfaceRegistryForTest(())
    with pytest.raises(LookupError):
        registry.bind("future.unknown.surface", object())


def test_agent_turn_is_the_canonical_narrow_surface_and_context_action_is_retired():
    from noetrium_platform.composition.workflows.agent_turn import agent_turn_trial_protocol
    from noetrium_platform.foundation.kernel.kernel import InMemoryMachineJournal

    agent_turn = agent_turn_trial_protocol(journal=InMemoryMachineJournal())
    assert agent_turn.surface_id == "agent_turn.operations.v1"

    import importlib.util
    assert importlib.util.find_spec(
        "noetrium_platform.composition.workflows.context_action"
    ) is None
