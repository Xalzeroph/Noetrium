from research.reproductions.adas_meta_agent_search import ADAS_META_AGENT_SEARCH_FIDELITY
from research.reproductions.live_swe_agent import LIVE_SWE_AGENT_FIDELITY
from research.reproductions.memevolve import MEMEVOLVE_FIDELITY


def test_adas_meta_agent_search_preserves_executable_archive_evolution() -> None:
    fidelity = ADAS_META_AGENT_SEARCH_FIDELITY
    assert fidelity.search_object == "executable_agent_code"
    assert fidelity.archive_driven_generation
    assert fidelity.reflection_passes_per_generation == 2
    assert fidelity.candidate_execution_required
    assert fidelity.failed_candidate_debug_regeneration
    assert fidelity.untrusted_generated_code


def test_memevolve_preserves_dual_memory_evolution_and_tournament_round() -> None:
    fidelity = MEMEVOLVE_FIDELITY
    assert fidelity.evolves_memory_content
    assert fidelity.evolves_memory_architecture
    assert fidelity.manual_phases == (
        "analyze_trajectories",
        "generate_memory_system",
        "create_implementation",
        "validate_system",
    )
    assert fidelity.round_process[-1] == "select_winner_as_next_base"
    assert fidelity.same_task_tournament_required
    assert fidelity.checkpoint_on_auto_evolution_error


def test_live_swe_agent_preserves_runtime_tool_creation_without_platform_policy() -> None:
    fidelity = LIVE_SWE_AGENT_FIDELITY
    assert fidelity.release_tag == "v1.0.0"
    assert fidelity.base_scaffold == "mini-swe-agent"
    assert fidelity.one_action_per_turn
    assert fidelity.action_interface == "bash"
    assert fidelity.runtime_tool_creation
    assert fidelity.created_tools_are_python_cli_programs
    assert fidelity.task_completion_command == "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
