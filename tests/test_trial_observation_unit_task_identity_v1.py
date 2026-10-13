"""The raw Trial observation sink must project typed Task Unit semantics."""
from noetrium import NoetriumUnit
from noetrium_platform.composition.experiment_observation import RawLakeStudyTrialObservationSink
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    StudyMetricObservation,
    TrialExecutionRequest,
    TrialExecutionReceipt,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    task_id, task_unit,
)


class _CapturingGateway:
    def __init__(self):
        self.records = []

    def register_producer(self, producer_id, system):
        assert producer_id
        assert system

    def capture(self, record):
        self.records.append(record)


def _receipt_with_task_units(task_ids):
    assignment = NoetriumUnit.make_structure(
        "assignment-probe",
        traits=("study.assignment",),
        parameters={"study_id": "trial-observation-probe", "variant_id": "v",
                    "repetition": 0, "seed": "probe-seed"},
    )
    tasks = tuple(
        task_unit(
            task_id_value,
            revision_id="v1",
            family="probe",
            schema_id="probe.v1",
            content_digest=None,
            content={"goal":"obtain an observed item"},
        )
        for task_id_value in task_ids
    )
    assert tuple(task_id(t) for t in tasks) == task_ids
    request = object.__new__(TrialExecutionRequest)
    for name, value in (
        ("request_digest", "a" * 64),
        ("run_id", "trial-observation-probe-run"),
        ("assignment", assignment),
        ("task_definitions", tasks),
    ):
        object.__setattr__(request, name, value)
    receipt = object.__new__(TrialExecutionReceipt)
    for name, value in (
        ("receipt_digest", "b" * 64),
        ("assignment_digest", "c" * 64),
        ("measurements", ()),
        ("evidence_refs", ()),
        ("verifier_receipt", None),
    ):
        object.__setattr__(receipt, name, value)
    observation = StudyMetricObservation(assignment=assignment, metrics=(("success", 1.0),))
    return request, receipt, observation


def test_raw_sink_uses_semantic_task_id_of_single_genuine_task_unit():
    gateway = _CapturingGateway()
    sink = RawLakeStudyTrialObservationSink(gateway)
    sink.publish(*_receipt_with_task_units(("physical-minecraft-task",)))
    assert len(gateway.records) == 1
    capture = gateway.records[0]
    assert capture.context.task_id == "physical-minecraft-task"
    assert capture.context.run_id == "trial-observation-probe-run"


def test_raw_sink_uses_none_for_multitask_trial_instead_of_fake_id():
    gateway = _CapturingGateway()
    sink = RawLakeStudyTrialObservationSink(gateway)
    sink.publish(*_receipt_with_task_units(("task-one", "task-two")))
    assert len(gateway.records) == 1
    assert gateway.records[0].context.task_id is None
