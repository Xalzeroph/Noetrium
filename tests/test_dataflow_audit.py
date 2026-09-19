import unittest
from noetrium_platform.foundation.governance.architecture import DataflowAudit, DataflowEdge
class DataflowTests(unittest.TestCase):
    def test_private_eval_to_method_is_rejected(self):
        e=(DataflowEdge("eval","j_eval","method","method_memory","bad"),)
        self.assertTrue(DataflowAudit(e,{("j_eval","method_memory")}).run())
    def test_platform_telemetry_is_allowed(self):
        e=(DataflowEdge("method","metrics","telemetry","metrics_store","observe"),)
        self.assertEqual(DataflowAudit(e,{("j_eval","method_memory")}).run(),())
if __name__=="__main__": unittest.main()
