from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.failure.api import DEFAULT_FAILURE_CATALOG
from noetrium_platform.infrastructure.reliability.forensics.runtime import CrashBundleBuilder, verify_crash_bundle
from noetrium_platform.infrastructure.reliability.failure.api import build_failure_from_spec
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.product.operator.runtime.parser import build_parser
from noetrium_platform.product.operator.query.runtime.route_runtime import route_runtime


class CrashBundleVerifyV90Tests(unittest.TestCase):
    def bundle(self,root:Path)->Path:
        spec=DEFAULT_FAILURE_CATALOG.require("METHOD","EVOLUTION_FAILURE","evolution")
        failure=build_failure_from_spec(
            spec=spec,component_id="method.evolution",context=ExecutionContext("run","trace","span"),exc=RuntimeError("candidate compile failed"),
        )
        out=root/"bundle.json"
        with ForensicStore(root/"forensics") as store:
            store.append_failure(failure)
            CrashBundleBuilder(store).publish(failure.failure_id,out)
        return out

    def test_valid_bundle_verifies_offline_and_cli_routes(self):
        with tempfile.TemporaryDirectory() as td:
            path=self.bundle(Path(td))
            report=verify_crash_bundle(path)
            self.assertTrue(report.valid)
            args=build_parser().parse_args(["crash-bundle-verify",str(path)])
            self.assertTrue(route_runtime(args).valid)

    def test_tampered_failure_is_detected_by_digest_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            path=self.bundle(Path(td)); data=json.loads(path.read_text())
            data["failure"]["cause_message"]="edited after export"
            path.write_text(json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2),encoding="utf-8")
            report=verify_crash_bundle(path)
            self.assertFalse(report.valid)
            self.assertIn("bundle digest mismatch",report.errors)
            self.assertIn("exact failure fingerprint mismatch",report.errors)

    def test_tampered_embedded_taxonomy_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            path=self.bundle(Path(td)); data=json.loads(path.read_text())
            data["taxonomy"]["spec"]["default_recovery"]="retry_operation"
            # Recompute outer digest to prove the semantic check is independent of transport hash.
            import hashlib
            base={k:v for k,v in data.items() if k!="bundle_digest"}
            data["bundle_digest"]=hashlib.sha256(json.dumps(base,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
            path.write_text(json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2),encoding="utf-8")
            report=verify_crash_bundle(path)
            self.assertFalse(report.valid)
            self.assertIn("embedded taxonomy spec digest mismatch",report.errors)


    def test_unreadable_bundle_error_redacts_secret_bearing_path(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            secret="super-secret-value"
            path=root/f"token={secret}"/"missing.json"
            report=verify_crash_bundle(path)
            self.assertFalse(report.valid)
            rendered=" ".join(report.errors)
            self.assertNotIn(secret, rendered)
            self.assertIn("<REDACTED>", rendered)
            self.assertIn("error_digest=", rendered)

if __name__=="__main__": unittest.main()
