from __future__ import annotations

from dataclasses import replace
import unittest

from noetrium_platform.capabilities.model.serving import build_host_inventory_receipt, compare_host_inventory_receipts
from test_server_runtime_control_v29 import runtime_host, HOST_ID


class HostResourceDeltaV98Tests(unittest.TestCase):
    def test_pre_to_post_delta_records_resource_consumption_without_changing_identity(self):
        before=runtime_host()
        gpus=tuple(replace(g,free_memory_bytes=g.free_memory_bytes-(8<<30)) for g in before.gpus)
        after=replace(
            before,
            captured_at_unix=2.0,
            memory=replace(before.memory,physical_available_bytes=before.memory.physical_available_bytes-(12<<30)),
            gpus=gpus,
            listening_ports=(8000,8001),
        )
        pre=build_host_inventory_receipt(HOST_ID,before,phase="pre_start")
        post=build_host_inventory_receipt(HOST_ID,after,phase="post_ready")
        delta=compare_host_inventory_receipts(pre,post)
        self.assertEqual(delta.host_memory_delta_bytes,-(12<<30))
        self.assertEqual(dict(delta.gpu_free_memory_delta_bytes)["GPU-1"],-(8<<30))
        self.assertEqual(delta.ports_added,(8000,8001))
        self.assertEqual(len(delta.delta_digest),64)

if __name__=="__main__": unittest.main()
