from __future__ import annotations

import unittest

from noetrium_platform.product.operator.query.runtime import FailureCatalogView
from noetrium_platform.product.operator.runtime.parser import build_parser
from noetrium_platform.product.operator.query.runtime.route_runtime import route_runtime


class FailureCatalogOperatorV84Tests(unittest.TestCase):
    def test_model_service_oom_query_exposes_exact_recovery_and_risks(self):
        result=FailureCatalogView().query(domain="model_serving",code="model_service_oom")
        self.assertEqual(result["count"],1)
        row=result["specs"][0]
        self.assertEqual(row["stage"],"service_process_exit")
        self.assertEqual(row["default_recovery"],"restart_exact_model")
        self.assertEqual(row["data_integrity_risk"],"low")
        self.assertEqual(row["comparability_risk"],"medium")
        self.assertEqual(row["scientific_validity_risk"],"medium")

    def test_domain_filter_returns_only_requested_domain(self):
        result=FailureCatalogView().query(domain="MODEL_SERVING")
        self.assertGreater(result["count"],1)
        self.assertTrue(all(x["domain"]=="MODEL_SERVING" for x in result["specs"]))

    def test_cli_route_is_read_only_and_requires_no_forensic_root(self):
        args=build_parser().parse_args(["failure-catalog","--code","MODEL_SERVICE_OOM"])
        result=route_runtime(args)
        self.assertEqual(result["count"],1)
        self.assertEqual(result["specs"][0]["code"],"MODEL_SERVICE_OOM")


if __name__=="__main__": unittest.main()
