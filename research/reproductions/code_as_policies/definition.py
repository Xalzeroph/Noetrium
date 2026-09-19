from __future__ import annotations

from noetrium_platform.research.reproduction import (
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
    package="code_as_policies",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="code-as-policies",
        title="Code as Policies: Language Model Programs for Embodied Control",
        paper_uri="https://arxiv.org/abs/2209.07753",
        year=2023,
        paper_revision=(
            "ICRA 2023 / paper-era google-research audit cut "
            "71896d4b6816983672aa6999e2dc92a3cfe904e4"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=(
            "embodied-robotics",
            "software-engineering",
        ),
        families=(
            "embodied",
            "hierarchical_code_generation",
            "language_model_programs",
            "robot_policy_synthesis",
        ),
        priority=1,
        benchmark_ids=(),
        platform_pressure=(
            "execution/workflow",
            "environment/embodied",
            "environment/software",
            "model/request",
            "participant/capability",
            "artifact/lineage",
            "experimentation/study",
        ),
        method_owned=(
            "language-to-policy code generation",
            "AST discovery of undefined direct-name function calls",
            "assignment-aware helper signatures",
            "recursive child-helper synthesis",
            "fixed/variable LMP namespace semantics",
            "session-context prompt semantics",
        ),
        platform_owned=(
            "MethodProgram host and journal authority",
            "model invocation and model identity",
            "isolated generated-program execution",
            "embodied environment API execution",
            "effect evidence and reconciliation",
            "artifact lineage",
            "Study/Experiment orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/code_as_policies/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("semantics"),
            path="research/reproductions/code_as_policies/hierarchy.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/code_as_policies/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/code_as_policies/source.py",
        ),
    ),
    primary_executable="research/reproductions/code_as_policies/program.py",
    reported_results=(),
    reference_baselines=(),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("substitution"),
            description=(
                "The paper-era helper discovery checks symbol existence with "
                "Python eval() over live fixed/variable dictionaries. The "
                "reproduction freezes the same scientific decision as an "
                "explicit known_names plus generated-helper namespace view, "
                "so discovery itself needs no host eval/exec."
            ),
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind("substitution"),
            description=(
                "The released recursive helper generator has no explicit "
                "depth/helper-count bound. The identity-bound synthesis agent "
                "adds fail-closed mechanical safety budgets without changing "
                "successful dependency-closure semantics inside those bounds."
            ),
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The notebook's exec_safe blocks the substrings 'import' and "
                "'__' and shadows exec/eval, but it is not process or container "
                "isolation. Formal Noetrium execution therefore requires a "
                "qualified isolated environment provider for generated policy "
                "programs rather than executing model code in the host process."
            ),
        ),
    ),
    blockers=(
        "Exact paper-era Codex/code-davinci-002 serving is not an immutable "
        "public model artifact.",
        "Formal embodied runs require a qualified isolated generated-program "
        "environment provider exposing the frozen robot/perception API surface.",
        "Matched physical-robot claims require the paper-era robot platforms, "
        "perception/control stacks, prompts, task cuts, and evaluation artifacts "
        "under immutable content identity.",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_code_as_policies_v1.py",
    ),
)

__all__ = ["REPRODUCTION"]
