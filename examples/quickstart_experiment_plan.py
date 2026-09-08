from __future__ import annotations

from noetrium.contracts.research import (
    ExperimentPlan,
    StudyProtocol,
    StudyVariantSpec,
    VariantBinding,
    VariantKind,
    StudyAssignment,
)
from noetrium.contracts import canonical_digest


def build_plan() -> ExperimentPlan:
    control = StudyVariantSpec(
        variant_id="control",
        kind=VariantKind.CONTROL,
        implementation_id="agent-baseline-v1",
        configuration_digest=canonical_digest({"temperature": 0.0}),
    )
    treatment = StudyVariantSpec(
        variant_id="treatment",
        kind=VariantKind.TREATMENT,
        implementation_id="agent-candidate-v1",
        configuration_digest=canonical_digest({"temperature": 0.2}),
    )
    protocol = StudyProtocol(
        study_id="noetrium-quickstart",
        workload_id="hello-agent-research",
        variants=(control, treatment),
        repetitions=3,
        seed_schedule_digest=canonical_digest(("seed-0", "seed-1", "seed-2")),
        metric_names=("success_rate", "steps"),
        task_manifest_digest=canonical_digest(("task-a", "task-b")),
    )
    bindings = (
        VariantBinding(control, canonical_digest("seed-schedule-v1"), canonical_digest("baseline-provider"), canonical_digest("none"), "reference"),
        VariantBinding(treatment, canonical_digest("seed-schedule-v1"), canonical_digest("candidate-provider"), canonical_digest("none"), "candidate"),
    )
    assignments = tuple(
        StudyAssignment(protocol.study_id, variant.variant_id, repetition, f"seed-{repetition}-{variant.variant_id}")
        for repetition in range(protocol.repetitions)
        for variant in protocol.variants
    )
    return ExperimentPlan.compile(protocol, bindings, assignments)


def main() -> None:
    plan = build_plan()
    plan.assert_consistent()
    variants = ",".join(item.variant_id for item in plan.protocol.variants)
    print(f"study={plan.protocol.study_id}")
    print(f"variants={variants}")
    print(f"repetitions={plan.protocol.repetitions}")
    print(f"protocol_digest={plan.protocol_digest}")
    print(f"plan_digest={plan.plan_digest}")
    print("plan_consistent=true")


if __name__ == "__main__":
    main()
