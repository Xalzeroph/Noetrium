from __future__ import annotations

from noetrium.contracts.systems.participant__capability import (
    CapabilityDescriptor,
    CapabilityRequest,
    ExecutionContext,
    GuardVerdict,
)
from research.reproductions.swe_agent_swebench import (
    SWE_AGENT_CURRENT_COMMAND_POLICY,
    SWE_AGENT_CURRENT_REFERENCE_FIDELITY,
    SWE_AGENT_PAPER_ERA_FIDELITY,
    SWEAgentCommandGuard,
    project_paper_era_history,
)


def test_swe_agent_paper_and_current_reference_are_not_conflated() -> None:
    paper = SWE_AGENT_PAPER_ERA_FIDELITY
    current = SWE_AGENT_CURRENT_REFERENCE_FIDELITY
    assert paper.source_artifact == "config/sweagent_0_7/07.yaml"
    assert paper.parser == "thought_action"
    assert paper.file_window_lines == 100
    assert paper.file_window_overlap == 2
    assert paper.history_observations_kept == 5
    assert paper.one_command_per_turn is True
    assert current.parser == "function_calling"
    assert current.execution_timeout_seconds == 30
    assert current.total_execution_timeout_seconds == 1800
    assert current.cache_control_last_n_messages == 2


def test_paper_era_history_elides_only_model_view_not_host_truth() -> None:
    source = [
        {"role": "user", "message_type": "observation", "content": f"obs-{index}\nline-2"}
        for index in range(8)
    ]
    original = [dict(row) for row in source]
    projected = project_paper_era_history(source)

    assert source == original
    assert projected.source_count == 8
    assert projected.elided_observation_count == 2
    assert projected.records[0]["content"] == "obs-0\nline-2"
    assert projected.records[1]["content"] == "Old environment output: (2 lines omitted)"
    assert projected.records[2]["content"] == "Old environment output: (2 lines omitted)"
    assert projected.records[3]["content"] == "obs-3\nline-2"
    assert projected.records[-1]["content"] == "obs-7\nline-2"


def test_paper_era_history_honors_keep_and_remove_tags() -> None:
    rows = [
        {"role": "user", "message_type": "observation", "content": "first"},
        {"role": "user", "message_type": "observation", "content": "keep", "tags": ["keep_output"]},
        {"role": "user", "message_type": "observation", "content": "middle"},
        {"role": "user", "message_type": "observation", "content": "force", "tags": ["remove_output"]},
        {"role": "user", "message_type": "observation", "content": "last-1"},
        {"role": "user", "message_type": "observation", "content": "last-2"},
        {"role": "user", "message_type": "observation", "content": "last-3"},
        {"role": "user", "message_type": "observation", "content": "last-4"},
    ]
    projected = project_paper_era_history(rows)
    assert projected.records[1]["content"] == "keep"
    assert projected.records[3]["content"].startswith("Old environment output:")


def test_current_swe_agent_command_policy_remains_downstream_semantics() -> None:
    policy = SWE_AGENT_CURRENT_COMMAND_POLICY
    assert policy.should_block("vim foo.py") is True
    assert policy.should_block("python") is True
    assert policy.should_block("python script.py") is False
    assert policy.should_block("radare2 binary") is True
    assert policy.should_block("radare2 binary -c 'aaa'") is False
    assert policy.should_block("grep -R TODO .") is False


def test_swe_agent_policy_plugs_into_generic_capability_guard() -> None:
    guard = SWEAgentCommandGuard()
    context = ExecutionContext("run:1", "trace:1", "span:1")
    descriptor = CapabilityDescriptor("software.command", "1", "json", "json")
    safe = CapabilityRequest("software.command", {"command": "grep -R TODO ."}, context)
    blocked = CapabilityRequest("software.command", {"command": "vim foo.py"}, context)

    assert guard.evaluate(descriptor, safe).verdict is GuardVerdict.ALLOW
    denied = guard.evaluate(descriptor, blocked)
    assert denied.verdict is GuardVerdict.DENY
    assert denied.reason_code == "unsupported_interactive_or_blocked_command"

    other_descriptor = CapabilityDescriptor("web.click", "1", "json", "json")
    other = CapabilityRequest("web.click", {"selector": "#submit"}, context)
    assert guard.evaluate(other_descriptor, other).verdict is GuardVerdict.ABSTAIN
