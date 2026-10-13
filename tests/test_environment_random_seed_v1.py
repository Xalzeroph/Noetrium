from dataclasses import replace

from noetrium_platform.composition.environment_capabilities.lifetime import environment_random_seed
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


def _context(*, condition_id: str, lifetime_id: str, repetition: int = 0, task_id: str | None = None):
    return ExecutionContext(
        run_id="run",
        trace_id="trace",
        span_id="span",
        study_id="study",
        condition_id=condition_id,
        repetition=repetition,
        assignment_seed="paired-seed",
        lifetime_id=lifetime_id,
        task_id=task_id,
    )


def test_assignment_environment_seed_is_treatment_and_lifetime_invariant():
    treatment = _context(condition_id="treatment", lifetime_id="life-treatment")
    control = _context(condition_id="control", lifetime_id="life-control")
    assert environment_random_seed(treatment, "minecraft:world", scope="assignment") == environment_random_seed(control, "minecraft:world", scope="assignment")


def test_assignment_environment_seed_changes_across_repetitions():
    first = _context(condition_id="treatment", lifetime_id="a", repetition=0)
    second = _context(condition_id="treatment", lifetime_id="b", repetition=1)
    assert environment_random_seed(first, "minecraft:world", scope="assignment") != environment_random_seed(second, "minecraft:world", scope="assignment")


def test_task_environment_seed_adds_task_identity_but_not_treatment_identity():
    a = _context(condition_id="treatment", lifetime_id="a", task_id="task-1")
    b = _context(condition_id="control", lifetime_id="b", task_id="task-1")
    c = _context(condition_id="control", lifetime_id="b", task_id="task-2")
    assert environment_random_seed(a, "minecraft:world", scope="task") == environment_random_seed(b, "minecraft:world", scope="task")
    assert environment_random_seed(a, "minecraft:world", scope="task") != environment_random_seed(c, "minecraft:world", scope="task")


def test_explicit_world_pairing_key_replaces_distinct_task_ids():
    setup = {
        "environment_pairing_id": "paired-protocol",
        "environment_task_setup": {"world_pairing_key": "world-1"},
    }
    a = replace(
        _context(condition_id="treatment", lifetime_id="a", task_id="vanilla-task"),
        participant_context=setup,
    )
    b = replace(
        _context(condition_id="control", lifetime_id="b", task_id="mirror-task"),
        participant_context=setup,
    )
    assert environment_random_seed(a, "minecraft:world", scope="task") == environment_random_seed(b, "minecraft:world", scope="task")
