from noetrium_platform.composition.experiment_runtime import build_experiment_runtime
from tests_support import FakeParticipantResolver
from tests_support import EmptyWorkflowSurfaceFactory, context_action_spec
import unittest

from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentTrialProtocolIdentityMismatch
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec


class AlternateTrialProtocol:
    protocol_id = "alternate.v1"
    surface_id = "empty.operations.v1"
    configuration_digest = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"

    def run(self, operations, context, *, task, input_kind, input_payload):
        raise AssertionError("identity mismatch must fail before workflow execution")


class ExperimentTrialProtocolIdentityV127Tests(unittest.TestCase):
    def test_workflow_changes_study_identity(self):
        default = context_action_spec(study_id="s", method_id="m", environment_id="e", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1)
        from dataclasses import replace
        alternate = replace(
            default, trial_protocol_id="alternate.v1",
            trial_protocol_configuration_digest="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        )
        self.assertNotEqual(default.identity_digest(), alternate.identity_digest())

    def test_runtime_rejects_workflow_drift_before_plugin_construction(self):
        runtime = build_experiment_runtime(participant_adapters=(), trial_protocol=AlternateTrialProtocol(), workflow_surface_factories=(EmptyWorkflowSurfaceFactory(),))
        frozen_default = context_action_spec(study_id="s", method_id="missing-method", environment_id="missing-env", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1)
        with self.assertRaises(ExperimentTrialProtocolIdentityMismatch):
            runtime.execute_cycle(
                frozen_default,
                task="x",
                input_kind="noop",
                input_payload=None,
            )

    def test_custom_workflow_requires_stable_id(self):
        class Anonymous:
            surface_id = "empty.operations.v1"
            configuration_digest = "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
            def run(self, operations, context, *, task, input_kind, input_payload):
                return None
        with self.assertRaises(ValueError):
            build_experiment_runtime(participant_adapters=(), trial_protocol=Anonymous(), workflow_surface_factories=(EmptyWorkflowSurfaceFactory(),))


if __name__ == "__main__":
    unittest.main()
