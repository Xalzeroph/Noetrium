from research.reproductions.adas_meta_agent_search import ADAS_META_AGENT_SEARCH_FIDELITY
from research.reproductions.live_swe_agent import (
    LIVE_SWE_AGENT_FIDELITY,
    LIVE_SWE_AGENT_METHOD_PROGRAM,
)
from research.reproductions.live_swe_agent.definition import (
    REPRODUCTION as LIVE_SWE_REPRODUCTION,
)
from research.reproductions.memevolve import (
    MEMEVOLVE_FIDELITY,
    MEMEVOLVE_METHOD_PROGRAM,
)
from research.reproductions.memevolve.definition import (
    REPRODUCTION as MEMEVOLVE_REPRODUCTION,
)
from research.reproductions.research_os import (
    compile_reproduction_research_program,
    is_research_os_executable,
    resolve_benchmark_split_consumers,
    resolve_execution_requirements,
)


def test_adas_meta_agent_search_preserves_executable_archive_evolution() -> None:
    fidelity = ADAS_META_AGENT_SEARCH_FIDELITY
    assert fidelity.search_object == "executable_agent_code"
    assert fidelity.archive_driven_generation
    assert fidelity.reflection_passes_per_generation == 2
    assert fidelity.initial_archive_size == 7
    assert fidelity.generation_budget == 30
    assert fidelity.candidate_execution_attempt_budget == 3
    assert fidelity.validation_size == 128
    assert fidelity.test_size == 800
    assert fidelity.shuffle_seed == 0
    assert fidelity.bootstrap_samples == 100000
    assert fidelity.bootstrap_confidence_level == 0.95
    assert fidelity.candidate_execution_required
    assert fidelity.failed_candidate_debug_regeneration
    assert fidelity.untrusted_generated_code
    assert fidelity.ineffective_generation_decrement


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



def test_live_swe_agent_method_program_keeps_online_tool_evolution_downstream() -> None:
    program = LIVE_SWE_AGENT_METHOD_PROGRAM

    assert program.configuration["runtime_tool_creation"] is True
    assert program.configuration["trajectory_reflection_before_tool_creation"] is True
    assert program.configuration["created_tools_are_python_cli_programs"] is True
    assert program.configuration["paper_default_step_limit"] == 0.0
    assert program.configuration["paper_default_cost_limit"] == 3.0
    assert program.required_capabilities == ("software.command",)
    assert program.graph.node("worker").agent_id == "live-swe-agent.worker"
    assert program.graph.node("tool_reflection").agent_id == (
        "live-swe-agent.tool-reflection"
    )


def test_live_swe_agent_enters_current_research_os_with_typed_swebench_split() -> None:
    assert is_research_os_executable(LIVE_SWE_REPRODUCTION)
    requirements = resolve_execution_requirements(LIVE_SWE_REPRODUCTION)

    assert requirements == ()
    assert resolve_benchmark_split_consumers(LIVE_SWE_REPRODUCTION) == (
        "study:build_live_swe_agent_study",
    )

    research_program = compile_reproduction_research_program(LIVE_SWE_REPRODUCTION)
    assert research_program.program_id == "live_swe_agent"
    assert tuple(node.node_id for node in research_program.nodes) == ("reproduction",)



def test_memevolve_method_program_preserves_meta_evolution_phases() -> None:
    program = MEMEVOLVE_METHOD_PROGRAM

    assert program.configuration["manual_phases"] == (
        "analyze_trajectories",
        "generate_memory_system",
        "create_implementation",
        "validate_system",
    )
    assert program.configuration["round_process"] == (
        "collect_base_logs",
        "generate_candidates",
        "tournament_base_plus_candidates",
        "finals_top_t_on_extended_tasks",
        "select_winner_as_next_base",
    )
    assert program.configuration["candidate_generation_independent"] is True
    assert program.configuration["same_task_tournament_required"] is True
    assert program.required_capabilities == ("workbench.candidate-program.execute",)


def test_memevolve_enters_current_research_os_with_typed_benchmark_split() -> None:
    assert is_research_os_executable(MEMEVOLVE_REPRODUCTION)
    requirements = resolve_execution_requirements(MEMEVOLVE_REPRODUCTION)

    assert requirements == ()
    assert resolve_benchmark_split_consumers(MEMEVOLVE_REPRODUCTION) == (
        "study:build_memevolve_study",
    )

    research_program = compile_reproduction_research_program(MEMEVOLVE_REPRODUCTION)
    assert research_program.program_id == "memevolve"
    assert tuple(node.node_id for node in research_program.nodes) == ("reproduction",)
