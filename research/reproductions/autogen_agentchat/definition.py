from __future__ import annotations

from noetrium_platform.research.reproduction import (
    ReferenceBaseline,
    ReportedResult,
    ReproductionAssetKind,
    ReproductionAssetRef,
    ReproductionCatalog,
    ReproductionDefinition,
    ReproductionDelta,
    ReproductionDeltaKind,
    ReproductionIdentity,
    ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package='autogen_agentchat',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='autogen',
        title='AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation',
        paper_uri='https://www.microsoft.com/en-us/research/publication/autogen-enabling-next-gen-llm-applications-via-multi-agent-conversation-framework/',
        year=2024,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('multi-agent', 'runtime-systems'),
        families=('multi_agent', 'human_agent_interaction', 'tool_use', 'code_execution'),
        priority=1,
        benchmark_ids=('multiagentbench',),
        platform_pressure=('execution/workflow', 'participant/agent', 'environment/software', 'execution', 'reliability/recovery', 'observability/telemetry'),
        method_owned=('conversable-agent reply policy', 'speaker selection policy', 'group-chat and user-proxy conversation semantics'),
        platform_owned=('participant lifecycle', 'message routing', 'human interruption', 'controlled code execution', 'effect evidence', 'recovery'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/autogen_agentchat/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/autogen_agentchat/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/autogen_agentchat/study.py',
        ),
    ),
    reported_results=(
    ),
    reference_baselines=(
    ),
    deltas=(
    ),
    blockers=('matched execution requires an exact paper-era model/prompt binding and an immutable deployment-qualified MultiAgentBench task/environment cut',),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_autogen_agentchat_fidelity_v1.py', 'tests/test_scientific_autogen_groupchat_method_program_v1.py'),
)

__all__ = ["REPRODUCTION"]
