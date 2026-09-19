from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.experiment.api import ExperimentTrialProtocolIdentity
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    MeasurementDefinition,
    ReplayLevel,
    ResearchStudyDefinition,
    Study,
    StudyModel,
    StudyParticipant,
    TrialBudget,
)
from research.benchmarks.webvoyager import (
    WEBVOYAGER_AGENT_Q_SURROGATE_REVISION,
    WEBVOYAGER_AGENT_Q_SURROGATE_SPLIT,
    WEBVOYAGER_AGENT_Q_SURROGATE_TASK_COUNT,
    WEBVOYAGER_BENCHMARK_ID,
)

from .fidelity import AGENT_Q_SURROGATE_FIDELITY

AGENT_Q_SURROGATE_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "agent-q.surrogate.webvoyager.browser-mcts.v1",
    canonical_digest({
        "benchmark_revision": WEBVOYAGER_AGENT_Q_SURROGATE_REVISION,
        "mcts": {
            "iterations": AGENT_Q_SURROGATE_FIDELITY.browser_invocation_iterations,
            "depth": AGENT_Q_SURROGATE_FIDELITY.browser_invocation_depth,
            "exploration": AGENT_Q_SURROGATE_FIDELITY.browser_invocation_exploration,
            "simulation": AGENT_Q_SURROGATE_FIDELITY.browser_invocation_simulation,
            "output": AGENT_Q_SURROGATE_FIDELITY.browser_invocation_output,
        },
        "reward": {
            "terminal": AGENT_Q_SURROGATE_FIDELITY.terminal_reward,
            "nonterminal": AGENT_Q_SURROGATE_FIDELITY.nonterminal_reward,
        },
        "terminal_judge_model": AGENT_Q_SURROGATE_FIDELITY.terminal_judge_model,
        "environment_iteration_policy": AGENT_Q_SURROGATE_FIDELITY.iteration_environment_policy,
        "dpo_pair_policy": AGENT_Q_SURROGATE_FIDELITY.dpo_pair_policy,
        "dpo_dom_limit": AGENT_Q_SURROGATE_FIDELITY.dpo_state_dom_character_limit,
    }),
)

def build_agent_q_surrogate_webvoyager_study(benchmark: BenchmarkTaskSet) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != WEBVOYAGER_BENCHMARK_ID:
        raise ValueError("Agent Q surrogate study requires WebVoyager")
    if benchmark.revision_id != WEBVOYAGER_AGENT_Q_SURROGATE_REVISION:
        raise ValueError("Agent Q surrogate study requires the frozen 643-task snapshot")
    if len(benchmark.selected_tasks(WEBVOYAGER_AGENT_Q_SURROGATE_SPLIT)) != WEBVOYAGER_AGENT_Q_SURROGATE_TASK_COUNT:
        raise ValueError("Agent Q surrogate WebVoyager lane requires all 643 tasks")

    return Study(
        project_id="agent-q-surrogate-reproduction",
        study_id="agent-q-surrogate-webvoyager-browser-mcts",
        benchmark=benchmark,
        benchmark_split_id=WEBVOYAGER_AGENT_Q_SURROGATE_SPLIT,
        method=StudyParticipant(
            role="browser_agent",
            kind="agent",
            implementation="agent-q",
            treatment="surrogate-browser-mcts",
            capabilities=("environment.act",),
            configurations=(
                "agent-q.surrogate.browser-mcts",
                "agent-q.surrogate.actor",
                "agent-q.surrogate.critic",
                "agent-q.surrogate.vision-judge",
            ),
        ),
        models={
            "actor": "model.agent-q-surrogate.actor",
            "critic": "model.agent-q-surrogate.critic",
            "vision_judge": "model.agent-q-surrogate.vision-judge",
        },
        measurements=(
            MeasurementDefinition.scalar(
                "terminal_judge_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="surrogate_terminal_judge_success",
                scale="binary",
                domain="webvoyager",
            ),
            MeasurementDefinition.scalar(
                "mcts_iterations",
                schema_id="noetrium.measurement.count.v1",
                unit="iteration",
                semantic_kind="search_compute",
                scale="count",
                domain="webvoyager",
            ),
            MeasurementDefinition.scalar(
                "generated_dpo_pairs",
                schema_id="noetrium.measurement.count.v1",
                unit="pair",
                semantic_kind="preference_data_generation",
                scale="count",
                domain="webvoyager",
            ),
        ),
        trial=AGENT_Q_SURROGATE_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=("surrogate-default",),
        limits=TrialBudget(
            "agent-q-surrogate-browser-depth-6",
            max_steps=AGENT_Q_SURROGATE_FIDELITY.browser_invocation_depth,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()

__all__ = ["AGENT_Q_SURROGATE_TRIAL_PROTOCOL", "build_agent_q_surrogate_webvoyager_study"]
