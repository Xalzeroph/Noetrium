from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentPhaseSpec, build_agent_phase_program
from .fidelity import WEBAGENT_R1_FIDELITY

WEBAGENT_R1_PHASES = (
    AgentPhaseSpec("warmup", "webagent_r1.warmup", "Initialize the web policy with behavior cloning or the paper's zero/CoT alternative."),
    AgentPhaseSpec("rollout", "webagent_r1.rollout", "Collect multi-turn web-interaction trajectories."),
    AgentPhaseSpec("reward", "webagent_r1.reward", "Score end-to-end task success for reinforcement learning."),
    AgentPhaseSpec("update", "webagent_r1.update", "Update the web policy using multi-turn RL trajectories."),
    AgentPhaseSpec("test_scale", "webagent_r1.test", "Run increased-interaction test-time scaling on WebArena-Lite tasks."),
)

WEBAGENT_R1_METHOD_PROGRAM = build_agent_phase_program(
    method_id="webagent-r1",
    implementation_version="2025-paper-protocol",
    schema_version="webagent-r1.phase-workflow.v1",
    phases=WEBAGENT_R1_PHASES,
    configuration={
        "paper_uri": WEBAGENT_R1_FIDELITY.paper_uri,
        "venue": WEBAGENT_R1_FIDELITY.venue,
        "year": WEBAGENT_R1_FIDELITY.year,
        "benchmark_ids": WEBAGENT_R1_FIDELITY.benchmark_ids,
    },
    evidence_obligations=("webagent-r1.phase-transcript", "webagent-r1.model-receipts"),
    metric_names=("task_success", "agent_phase_count"),
    artifact_kinds=("webagent-r1_trajectory",),
)
__all__ = ["WEBAGENT_R1_METHOD_PROGRAM", "WEBAGENT_R1_PHASES"]
