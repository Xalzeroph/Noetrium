from pathlib import Path
import unittest

from noetrium_platform.research.execution.workflow.implementations.context_action import (
    context_action_trial_protocol,
)
from noetrium_platform.research.execution.workflow.runtime.program_trial import (
    RuntimeProgramTrialProtocol,
)
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime


class StudyWorkflowDecouplingV126Tests(unittest.TestCase):
    def test_default_workflow_is_a_program_backed_replaceable_policy(self):
        protocol = context_action_trial_protocol()
        self.assertIsInstance(protocol, RuntimeProgramTrialProtocol)
        root = Path(__file__).resolve().parents[1]
        runtime_source = (
            root
            / "noetrium_platform"
            / "research"
            / "experimentation"
            / "experiment"
            / "runtime"
            / "engine.py"
        ).read_text(encoding="utf-8")
        composition_source = (
            root
            / "noetrium_platform"
            / "composition"
            / "experiment_runtime.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("trial_protocol=", runtime_source)
        self.assertNotIn("participant_runtime", runtime_source)
        self.assertIn("RuntimeProgramTrialProtocol", composition_source)
        self.assertIn("build_experiment_runtime", composition_source)
        self.assertNotIn('environment.observe"', runtime_source)
        self.assertNotIn('method.recall"', runtime_source)


if __name__ == "__main__":
    unittest.main()
