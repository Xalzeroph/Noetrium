from __future__ import annotations

from noetrium import api


def build_plan() -> api.ExperimentPlan:
    control = api.StudyVariantSpec(
        variant_id="control",
        kind=api.VariantKind.CONTROL,
        implementation_id="agent-baseline-v1",
        configuration_digest=api.canonical_digest({"temperature": 0.0}),
    )
    treatment = api.StudyVariantSpec(
        variant_id="treatment",
        kind=api.VariantKind.TREATMENT,
        implementation_id="agent-candidate-v1",
        configuration_digest=api.canonical_digest({"temperature": 0.2}),
    )
    protocol = api.StudyProtocol(
        study_id="noetrium-quickstart",
        workload_id="hello-agent-research",
        variants=(control, treatment),
        repetitions=3,
        seed_schedule_digest=api.canonical_digest(("seed-0", "seed-1", "seed-2")),
        metric_names=("success_rate", "steps"),
        task_manifest_digest=api.canonical_digest(("task-a", "task-b")),
        budget_tiers=("standard",),
        concurrency_policy=api.StudyConcurrencyPolicy.serial_shared_v1(
            repetition_timeout_seconds=3600.0
        ),
    )
    bindings = (
        api.VariantBinding(control, api.canonical_digest("seed-schedule-v1"), api.canonical_digest("baseline-provider"), api.canonical_digest("none"), "reference"),
        api.VariantBinding(treatment, api.canonical_digest("seed-schedule-v1"), api.canonical_digest("candidate-provider"), api.canonical_digest("none"), "candidate"),
    )
    assignments = tuple(
        api.StudyAssignment(protocol.study_id, variant.variant_id, repetition, f"seed-{repetition}-{variant.variant_id}")
        for repetition in range(protocol.repetitions)
        for variant in protocol.variants
    )
    return api.ExperimentPlan.compile(protocol, bindings, assignments)


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
