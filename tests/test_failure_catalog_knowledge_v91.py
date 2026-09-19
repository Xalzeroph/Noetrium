from __future__ import annotations

import unittest

from noetrium_platform.infrastructure.reliability.failure.api import DEFAULT_FAILURE_CATALOG
from noetrium_platform.product.operator.query.runtime import FailureCatalogView


class FailureCatalogKnowledgeV91Tests(unittest.TestCase):
    def test_default_catalog_has_complete_operator_knowledge(self):
        self.assertEqual(DEFAULT_FAILURE_CATALOG.knowledge_errors(),())

    def test_oom_entry_exposes_owner_focus_and_commands(self):
        result=FailureCatalogView().query(domain="MODEL_SERVING",code="MODEL_SERVICE_OOM")
        row=result["specs"][0]
        self.assertEqual(row["owner"],"model_os")
        self.assertIn("gpu_memory",row["diagnostic_focus"])
        self.assertIn("runtime-status",row["operator_checks"])
        self.assertTrue(row["description"])

if __name__=="__main__": unittest.main()
