from pathlib import Path
import tempfile
import unittest

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.infrastructure.lifecycle.api import (
    LifecyclePhase,
    LifecycleSpec,
)
from noetrium_platform.infrastructure.lifecycle.runtime import (
    ComponentHealthRecord,
    ComponentHealthStore,
    HealthClassification,
    HealthMonitor,
    LifecycleExecutor,
    LifecycleGraphError,
    LifecycleStartError,
    ResourceHealth,
)


class _C:
    def __init__(self,cid,deps=(),calls=None,fail_start=False,fail_stop=False):
        self.lifecycle_spec=LifecycleSpec(cid,tuple(deps),heartbeat_interval_s=5); self.calls=calls if calls is not None else []; self.fail_start=fail_start; self.fail_stop=fail_stop
    def start(self,ctx):
        self.calls.append(("start",self.lifecycle_spec.component_id))
        if self.fail_start: raise RuntimeError("start defect")
        return (f"ready:{self.lifecycle_spec.component_id}",)
    def stop(self,ctx):
        self.calls.append(("stop",self.lifecycle_spec.component_id))
        if self.fail_stop: raise RuntimeError("stop defect")
        return (f"stopped:{self.lifecycle_spec.component_id}",)


class LifecycleV18Tests(unittest.TestCase):
    def ctx(self): return ExecutionContext("r","t","s")

    def test_topological_order_drives_start_and_reverse_stop(self):
        calls=[]; mgr=LifecycleExecutor((_C("study",("method","env"),calls),_C("env",("model",),calls),_C("model",(),calls),_C("method",("model",),calls)))
        report=mgr.start_all(self.ctx()); self.assertEqual(report.start_order,("model","env","method","study"))
        mgr.stop_all(self.ctx())
        self.assertEqual(calls,[('start','model'),('start','env'),('start','method'),('start','study'),('stop','study'),('stop','method'),('stop','env'),('stop','model')])

    def test_graph_errors_happen_before_any_side_effect(self):
        calls=[]
        with self.assertRaises(LifecycleGraphError): LifecycleExecutor((_C("a",("missing",),calls),))
        self.assertEqual(calls,[])
        with self.assertRaises(LifecycleGraphError): LifecycleExecutor((_C("a",("b",),calls),_C("b",("a",),calls)))
        self.assertEqual(calls,[])

    def test_failed_start_rolls_back_started_components_and_preserves_rollback_failure(self):
        calls=[]; mgr=LifecycleExecutor((_C("a",(),calls,fail_stop=True),_C("b",("a",),calls,fail_start=True)))
        with self.assertRaises(LifecycleStartError) as cm: mgr.start_all(self.ctx())
        self.assertEqual(cm.exception.component_id,"b"); self.assertEqual(cm.exception.started,("a",)); self.assertEqual(cm.exception.rollback_failures[0].component_id,"a")
        self.assertEqual(calls,[('start','a'),('start','b'),('stop','a')])

    def test_health_monitor_distinguishes_heartbeat_stall(self):
        rec=ComponentHealthRecord("model",LifecyclePhase.READY,"g",123,"pid:123:start:9",5,100,100,resource=ResourceHealth(rss_bytes=10),updated_at=100)
        healthy=HealthMonitor().assess(rec,now=110); self.assertEqual(healthy.classification,HealthClassification.READY)
        stalled=HealthMonitor().assess(rec,now=116); self.assertEqual(stalled.classification,HealthClassification.STALLED); self.assertIn("heartbeat",stalled.reason)

    def test_health_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"health.json"; rec=ComponentHealthRecord("c",LifecyclePhase.READY,"g",1,"id",2,3,4,"f",ResourceHealth(10,20.0,3,4,5),6)
            store=ComponentHealthStore(path); store.write(rec); loaded=store.read(); self.assertEqual(loaded,rec)

if __name__=='__main__': unittest.main()
