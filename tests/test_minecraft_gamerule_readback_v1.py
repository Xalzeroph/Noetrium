from __future__ import annotations

import pytest
from noetrium_platform.capabilities.environment.minecraft.providers.scenario import (
    _scenario_response_matches,
)


@pytest.mark.parametrize(
    "response",
    [
        "Gamerule spawnRadius is currently set to: 0",
        "Gamerule spawnRadius is now set to: 0",
        "spawnRadius = 0",
    ],
)
def test_native_and_compact_rule_readbacks_prove_the_same_scalar(response):
    assert _scenario_response_matches(
        "spawnRadius = 0", response, "gamerule spawnRadius"
    )


@pytest.mark.parametrize(
    "response",
    [
        "Gamerule spawnRadius is currently set to: 10",
        "Gamerule spawnRadius is currently set to: 01",
        "Gamerule randomTickSpeed is currently set to: 0",
        "spawnRadius = 0 but failed",
        "Error: spawnRadius = 0",
        "unknown command",
    ],
)
def test_wrong_values_rules_and_unproven_fragments_are_rejected(response):
    assert not _scenario_response_matches(
        "spawnRadius = 0", response, "gamerule spawnRadius"
    )


def test_boolean_readback_and_rule_identity_are_checked():
    assert _scenario_response_matches(
        "doDaylightCycle = false",
        "Gamerule doDaylightCycle is currently set to: false",
        "gamerule doDaylightCycle",
    )
    assert not _scenario_response_matches(
        "doDaylightCycle = false",
        "Gamerule doDaylightCycle is currently set to: true",
        "gamerule doDaylightCycle",
    )
    assert not _scenario_response_matches(
        "spawnRadius = 0", "spawnRadius = 0", "gamerule randomTickSpeed"
    )


def test_other_scenario_assertions_keep_their_declared_literal_semantics():
    assert _scenario_response_matches(
        "Time set", "Time set to 1000", "time query daytime"
    )
    assert not _scenario_response_matches(
        "success", "permission denied", "data get entity player"
    )
