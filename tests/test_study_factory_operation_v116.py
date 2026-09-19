from __future__ import annotations

from tests_support import FakeParticipantResolver
from tests_support import context_action_runtime

from tests_support import context_action_spec

from pathlib import Path
import tempfile
import unittest

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.composition.operation_forensics import OperationForensicFailureSink
from noetrium_platform.composition.context_action import context_action_failure_classifier_chain
from noetrium_platform.foundation.kernel.kernel import OperationExecutor, OperationFailure
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec


class BrokenFactory:
    def __call__(self):
        raise RuntimeError("factory exploded")


class StudyFactoryOperationV116Tests(unittest.TestCase):
    def test_method_factory_failure_crosses_operation_boundary_and_is_forensic(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); methods=FakeParticipantResolver(); environments=FakeParticipantResolver(); methods.register("method", "broken",BrokenFactory())
            store=ForensicStore(root/"forensics")
            runtime=context_action_runtime(methods,environments,operation_executor=OperationExecutor(OperationForensicFailureSink(store, classifier=context_action_failure_classifier_chain())))
            spec=context_action_spec(study_id="study", method_id="broken", environment_id="unused", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1)
            with self.assertRaises(OperationFailure) as raised:
                runtime.execute_cycle(spec,task="x",input_kind="a",input_payload={})
            self.assertIn("method.resolve",str(raised.exception))
            self.assertEqual(store.failures.verify()[0],1)
            failures=store.failures.verified_payloads_after(0).payloads
            self.assertEqual(len(failures),1)
            failure=failures[0]
            self.assertEqual(failure["failure_domain"],"PARTICIPANT")
            self.assertEqual(failure["failure_code"],"RESOLUTION_FAILURE")
            self.assertEqual(failure["operation_type"],"method.resolve")
            store.close()


if __name__ == "__main__": unittest.main()
