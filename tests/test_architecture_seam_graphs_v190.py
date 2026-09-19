from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import unittest

from tests_support import repository_architecture_report


class ArchitectureSeamGraphsV190Tests(unittest.TestCase):
    def test_report_contains_generated_capability_operation_and_event_graphs(self):
        root=Path(__file__).resolve().parents[1]
        report=repository_architecture_report()
        capability={(x.seam_id,x.relation) for x in report.capability_graph}
        operations={x.seam_id for x in report.operation_graph}
        events={x.seam_id for x in report.event_graph}
        event_edges={(x.seam_id,x.relation) for x in report.event_graph}
        self.assertIn(("prompt.runtime","provides"),capability)
        self.assertIn("agent.run_turn",operations)
        self.assertIn("capability.invoke",operations)
        self.assertIn("FAILURE_RECORDED",events)
        self.assertIn("OPERATION_AUXILIARY_FAILURE",events)
        self.assertIn(("OPERATION_STARTED","emits"),event_edges)
        self.assertIn(("OPERATION_FAILED","consumes"),event_edges)

    def test_typed_graphs_preserve_json_report_shape(self):
        rendered=asdict(repository_architecture_report())
        self.assertIsInstance(rendered["capability_graph"][0], dict)
        self.assertEqual(
            set(rendered["capability_graph"][0]),
            {"kind","seam_id","module","relation","path","line"},
        )
        self.assertEqual(
            set(rendered["system_graph"][0]),
            {"source","target","relation"},
        )
        json.dumps(rendered, sort_keys=True)


if __name__ == "__main__": unittest.main()
