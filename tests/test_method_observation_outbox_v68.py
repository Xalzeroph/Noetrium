from __future__ import annotations

from noetrium_platform.capabilities.participant.method.runtime import MethodObservationOutbox

import unittest

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.capabilities.participant.method.api import (
    MethodObservation,
    MethodObservationDeliveryError,
)


class FlakySink:
    def __init__(self)->None:
        self.fail=True
        self.rows=[]
    def record(self,observation):
        if self.fail:
            raise OSError("telemetry unavailable")
        if observation.observation_id not in {x.observation_id for x in self.rows}:
            self.rows.append(observation)
        return len(self.rows)


class MethodObservationOutboxV68Tests(unittest.TestCase):
    def observation(self):
        return MethodObservation.build(
            ExecutionContext("run","trace","span"),
            "method-x",
            "session-x",
            "mutation",
            {"revision":1},
        )

    def test_delivery_failure_retains_exact_observation_for_replay(self):
        sink=FlakySink()
        outbox=MethodObservationOutbox(sink)
        obs=self.observation()
        with self.assertRaises(MethodObservationDeliveryError) as cm:
            outbox.deliver(obs)
        self.assertTrue(cm.exception.mutation_committed)
        self.assertEqual(outbox.snapshot(),(obs,))
        sink.fail=False
        self.assertEqual(outbox.flush(),(obs.observation_id,))
        self.assertEqual(outbox.snapshot(),())
        self.assertEqual(tuple(sink.rows),(obs,))

    def test_restore_rejects_duplicate_observation_ids(self):
        sink=FlakySink()
        outbox=MethodObservationOutbox(sink)
        obs=self.observation()
        with self.assertRaises(ValueError):
            outbox.restore((obs,obs))


if __name__=="__main__":
    unittest.main()
