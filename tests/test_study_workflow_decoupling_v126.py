from pathlib import Path
import unittest

from noetrium_platform.composition.workflows.context_action import (
    context_action_trial_protocol,
)
from noetrium_platform.research.execution.workflow.api import (
    ExecutionTrialProtocolPort,
)
from noetrium_platform.research.experimentation.lifecycle.experiment.runtime import ExperimentRuntime


class StudyWorkflowDecouplingV126Tests(unittest.TestCase):
    def test_default_workflow_is_a_program_backed_replaceable_policy(self):
        protocol = context_action_trial_protocol()
        self.assertIsInstance(protocol, ExecutionTrialProtocolPort)
        root = Path(__file__).resolve().parents[1]
        runtime_source = (
            root
            / "noetrium_platform"
            / "research"
            / "experimentation"
            / "lifecycle"
            / "experiment"
            / "runtime"
            / "engine.py"
        ).read_text(encoding="utf-8")
        retired_root = (
            root
            / "noetrium_platform"
            / "composition"
            / "experiment_runtime.py"
        )
        self.assertNotIn("trial_protocol=", runtime_source)
        self.assertNotIn("participant_runtime", runtime_source)
        self.assertFalse(retired_root.exists())
        self.assertNotIn('environment.observe"', runtime_source)
        self.assertNotIn('method.recall"', runtime_source)


if __name__ == "__main__":
    unittest.main()
