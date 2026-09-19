import unittest
from noetrium_platform.evidence.observability.telemetry.event.api import EventDefinition, RuntimeStage
from noetrium_platform.evidence.observability.telemetry.event.runtime import EventRegistry, RuntimeStageAudit

class EventEmitterAuditTests(unittest.TestCase):
    def test_declared_event_without_emitter_fails(self):
        r=EventRegistry(); r.register(EventDefinition("A",("run_id",),"a"))
        self.assertTrue(r.audit_emitters())
        r.bind_emitter("A","c")
        self.assertEqual(r.audit_emitters(),())
    def test_stage_triplet_must_exist(self):
        a=RuntimeStageAudit((RuntimeStage("llm","llm","S","OK","FAIL"),),{"S","OK","FAIL"})
        self.assertEqual(a.run(),())
        b=RuntimeStageAudit((RuntimeStage("llm","llm","S","OK","MISSING"),),{"S","OK","FAIL"})
        self.assertTrue(b.run())

if __name__=="__main__": unittest.main()
