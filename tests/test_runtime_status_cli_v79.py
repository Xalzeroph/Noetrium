from __future__ import annotations

from runtime_manager_test_support import make_runtime_control_store
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
import unittest

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.product.operator.query.runtime.route_runtime import route_runtime
from noetrium_platform.product.operator.runtime.parser import build_parser
from noetrium_platform.infrastructure.lifecycle.launch_control.heartbeat_storage import FileServiceHeartbeatStore
from noetrium_platform.infrastructure.lifecycle.launch_control import RuntimeControlStore, RuntimeTxnPhase
from noetrium_platform.infrastructure.lifecycle.launch_control.heartbeat import ServiceHeartbeat
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime import ServicePhase
from noetrium_platform.infrastructure.lifecycle.service.runtime.service_state_contracts import ServiceSupervisorState

from test_server_runtime_control_v29 import deployment


class RuntimeStatusCLIV79Tests(unittest.TestCase):
    def test_runtime_status_layout_drives_one_joined_operator_query(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); d=deployment("planner","GPU-0")
            runtime=make_runtime_control_store(root/"runtime.json")
            s=runtime.create("ctl","manifest")
            runtime.write(replace(s,phase=RuntimeTxnPhase.SUCCEEDED))

            hb=FileServiceHeartbeatStore(root/"heartbeats")
            hb.write(ServiceHeartbeat(
                d.deployment_id,d.stack.digest(),123,"start","argv",True,
                d.certificate.digest(),time.time(),
            ))
            service_path=root/"service.json"
            FileServiceStateStore(service_path).write(ServiceSupervisorState(
                d.deployment_id,"contract",ServicePhase.RUNNING,1,None,
                "ready://planner","capture://stdout","capture://stderr",
                time.time(),None,None,time.time(),time.time(),
            ))
            with ForensicStore(root/"forensics"):
                pass

            layout=root/"runtime_status.json"
            layout.write_text(json.dumps({
                "runtime_state":str(root/"runtime.json"),
                "runtime_history":str(root/"runtime.json.history.jsonl"),
                "heartbeat_root":str(root/"heartbeats"),
                "resource_authority":str(root/"resource-authority.sqlite"),
                "forensic_root":str(root/"forensics"),
                "heartbeat_max_age_seconds":30,
                "deployments":[{
                    "deployment_id":d.deployment_id,
                    "stack_digest":d.stack.digest(),
                    "qualification_digest":d.certificate.digest(),
                }],
                "services":[{"service_id":d.deployment_id,"state_path":str(service_path),"start_intent_root":str(service_path.with_name(service_path.name+".start-intents"))}],
            }),encoding="utf-8")

            args=build_parser().parse_args(["runtime-status",str(layout)])
            result=route_runtime(args)
            self.assertEqual(result["status"],"ready")
            names={x["subsystem"] for x in result["subsystems"]}
            self.assertIn("model:planner",names)
            self.assertIn("forensics",names)

    def test_runtime_recovery_plan_is_read_only_machine_routable(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            runtime=make_runtime_control_store(root/"runtime.json")
            runtime.create("ctl","manifest")
            with ForensicStore(root/"forensics"):
                pass
            layout=root/"runtime_status.json"
            layout.write_text(json.dumps({
                "runtime_state":str(root/"runtime.json"),
                "runtime_history":str(root/"runtime.json.history.jsonl"),
                "heartbeat_root":str(root/"heartbeats"),
                "resource_authority":str(root/"resource-authority.sqlite"),
                "forensic_root":str(root/"forensics"),
                "deployments":[],
                "services":[],
            }),encoding="utf-8")
            before=(root/"runtime.json").read_bytes()
            args=build_parser().parse_args(["runtime-recovery-plan",str(layout)])
            result=route_runtime(args)
            self.assertEqual(result["schema_version"],"runtime-recovery-plan.v1")
            self.assertEqual(result["status"]["schema_version"],"platform-status.v2")
            actions=[row["action"] for row in result["recovery"]["recommendations"]]
            self.assertIn("reconcile_runtime_transaction",actions)
            self.assertEqual((root/"runtime.json").read_bytes(),before)


    def test_duplicate_deployment_identity_in_layout_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); layout=root/"layout.json"
            row={"deployment_id":"d","stack_digest":"s","qualification_digest":"q"}
            layout.write_text(json.dumps({
                "runtime_state":"r","runtime_history":"rh","heartbeat_root":"h","resource_authority":"l","forensic_root":"f",
                "deployments":[row,row],"services":[],
            }),encoding="utf-8")
            args=build_parser().parse_args(["runtime-status",str(layout)])
            with self.assertRaises(ValueError): route_runtime(args)


if __name__=="__main__": unittest.main()
