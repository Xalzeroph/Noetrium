"""One durable Method component handles distinct requests without caching old results."""
import unittest

from noetrium_platform.foundation.kernel.kernel import InMemoryMachineJournal, MachineStatus
from noetrium_platform.foundation.kernel.kernel.unit_host import BoundExecutableUnit
from noetrium_platform.research.execution.method.components import research_component_operations
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel.unit_activation import UnitActivationRegistry



def fixture_component(
    host_id: str, dispatch, *, version: str, state_schema: str, operation_type: str
) -> NoetriumUnit:
    """Build a generic persistent research component without downstream dependencies."""
    implementation = NoetriumUnit.from_python_callable(
        f"{host_id}.dispatch", dispatch, implementation_type="method.handler"
    )
    handler_symbol = NoetriumUnit.make_symbol(
        "handler", traits=("method.implementation",), implementation=implementation
    )
    node = NoetriumUnit.make_structure(
        "dispatch",
        traits=("unit.operation",),
        parameters={
            "operation": operation_type,
            "configuration": {"await_next_request": True},
            "max_visits": None,
            "required_capabilities": (),
        },
        symbols=(handler_symbol,),
    )
    return NoetriumUnit.make_structure(
        host_id,
        traits=("unit.executable", "method.component"),
        parameters={
            "domain": "memory",
            "version": version,
            "state_schema": state_schema,
            "entrypoint": "dispatch",
            "required_capabilities": (),
        },
        members=(node,),
    )

def counting_dispatch(call):
    count = int(call.data.get("counter", 0)) + 1
    return {"value": {"count": count, "operation": call.payload["operation"]},
            "state_update": {"counter": count}}


class PersistentComponentCycleTests(unittest.TestCase):
    def test_three_requests_same_machine_write_three_durable_transitions(self):
        program = fixture_component(
            "fixture.persistent.counter", counting_dispatch, version="1",
            state_schema="fixture.state.v1", operation_type="fixture.dispatch",
        )
        host = BoundExecutableUnit(
            host_id="fixture.persistent.counter", unit=program,
            operations=research_component_operations(program),
            journal=InMemoryMachineJournal(),
        )
        outputs=[]
        for operation in ("recall", "ingest", "apply_meta"):
            receipt=host.execute(
                machine_id="fixture:memory:one",
                instance_identity={"scope_key": "shared-study-cohort"},
                binding=None,initial_data={},payload={"operation": operation},
                command_id_prefix="fixture:"+operation,
                resume_waiting=True,
            )
            self.assertEqual(receipt.status, MachineStatus.WAITING)
            outputs.append((receipt.previous_value,receipt.revision,receipt.data["counter"]))
        self.assertEqual([r[0]["operation"] for r in outputs],["recall","ingest","apply_meta"])
        self.assertEqual([r[0]["count"] for r in outputs],[1,2,3])
        self.assertEqual([r[2] for r in outputs],[1,2,3])
        self.assertEqual(sorted({r[1] for r in outputs}),[r[1] for r in outputs])
        self.assertEqual(len({r[1] for r in outputs}),3)

    def test_child_receipts_have_nonoverlapping_causal_transition_ranges(self):
        program = fixture_component(
            "fixture.persistent.activation", counting_dispatch, version="1",
            state_schema="fixture.state.v1", operation_type="fixture.dispatch",
        )
        host = BoundExecutableUnit(
            host_id="fixture.persistent.activation", unit=program,
            operations=research_component_operations(program),
            journal=InMemoryMachineJournal(),
        )
        registry = UnitActivationRegistry()
        registry.register_static(host)
        activation = registry.runtime()
        receipts = []
        for name in ("recall", "ingest", "apply_meta"):
            receipt = activation.execute({
                "host_id": "fixture.persistent.activation",
                "parent_machine_id": "parent:scientific-task",
                "child_machine_id": "child:persistent:memory",
                "instance_identity": {"cohort": "one"},
                "initial_data": {},
                "payload": {"operation": name},
                "command_id_prefix": "cmd:" + name,
                "resume_waiting": True,
                "failure_policy": "fail_parent",
            })
            self.assertEqual(receipt.status, MachineStatus.WAITING)
            receipts.append(receipt)
        self.assertEqual(
            [x.result["operation"] for x in receipts],
            ["recall", "ingest", "apply_meta"],
        )
        self.assertEqual([x.result["count"] for x in receipts], [1, 2, 3])
        for before, after in zip(receipts, receipts[1:]):
            self.assertGreater(
                after.link.child_transition_start,
                before.link.child_transition_end,
            )
        self.assertEqual(
            [x.link.parent_machine_id for x in receipts],
            ["parent:scientific-task"] * 3,
        )


if __name__ == "__main__":
    unittest.main()
