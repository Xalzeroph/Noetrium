import unittest
from noetrium_platform.evidence.observability.telemetry.metric.api import MetricDefinition, MetricKind
from noetrium_platform.evidence.observability.telemetry.metric.composition import build_default_registry
from noetrium_platform.evidence.observability.telemetry.metric.runtime import MetricRegistry, TelemetryAudit

class TelemetryAuditTests(unittest.TestCase):
    def test_default_catalog_clean(self):
        self.assertEqual(TelemetryAudit(build_default_registry()).run(), ())
    def test_request_id_dimension_rejected(self):
        r=MetricRegistry(); r.register(MetricDefinition("bad",MetricKind.COUNTER,"count",("request_id",),"bad"))
        self.assertTrue(TelemetryAudit(r).run())

if __name__ == "__main__": unittest.main()
