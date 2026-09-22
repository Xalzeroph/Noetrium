from __future__ import annotations

from pathlib import Path
import json
import tempfile

from noetrium_platform.foundation.governance.architecture.concurrency_boundary_invariants import (
    audit_concurrency_boundary_invariants,
)
from noetrium_platform.foundation.governance.system_registry.api import system_catalog


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_execution_policy_is_one_component_of_execution_authority() -> None:
    execution = next(
        item for item in system_catalog() if item.identity.key == "execution"
    )
    components = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "noetrium_platform/foundation/governance/system_registry/components.json"
        ).read_text(encoding="utf-8")
    )
    policy = components["execution/policy"]
    assert "execution/policy" in execution.components
    assert policy["canonical_authority"] == "execution"
    assert "admission" in policy["owns"].lower()
    assert {
        facet["key"] for facet in policy.get("internal_facets", ())
    } == {"execution/policy/scheduling"}


def test_business_system_cannot_import_concurrency_provider_or_deep_provider_port() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(
            root,
            "noetrium_platform/infrastructure/resources/example/runtime/service.py",
            "from noetrium_platform.foundation.kernel.concurrency.providers import BoundedThreadExecutor\n"
            "from noetrium_platform.foundation.kernel.concurrency.api.ports import ExecutorProviderPort\n",
        )
        rows = audit_concurrency_boundary_invariants(root)
        assert len(rows) == 2
        assert {row.invariant for row in rows} == {"structured_concurrency_provider_firewall"}


def test_business_system_may_depend_on_public_task_group_contract() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(
            root,
            "noetrium_platform/infrastructure/resources/example/runtime/service.py",
            "from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort\n",
        )
        assert audit_concurrency_boundary_invariants(root) == []


def test_concurrency_system_itself_may_use_provider_ports() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(
            root,
            "noetrium_platform/foundation/kernel/concurrency/runtime/runtime.py",
            "from noetrium_platform.foundation.kernel.concurrency.api.ports import ExecutorProviderPort\n",
        )
        assert audit_concurrency_boundary_invariants(root) == []


def test_business_system_cannot_use_legacy_executor_specific_task_group_methods() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(
            root,
            "noetrium_platform/infrastructure/resources/example/runtime/service.py",
            "def run(group):\n"
            "    group.submit_blocking('a', lambda context: None)\n"
            "    group.submit_cpu('b', abs, -1)\n"
            "    group.submit_serial('lane', 'c', lambda context: None)\n",
        )
        rows = audit_concurrency_boundary_invariants(root)
        assert len(rows) == 3
        assert {row.invariant for row in rows} == {"legacy_concurrency_execution_seam"}


def test_concurrency_cannot_import_execution_policy_system() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(
            root,
            "noetrium_platform/foundation/kernel/concurrency/runtime/runtime.py",
            "from noetrium_platform.research.execution.policy.api import ExecutionAdmissionPort\n"
            "from noetrium_platform.research.execution.policy.api import ExecutionPriority\n",
        )
        rows = audit_concurrency_boundary_invariants(root)
        assert len(rows) == 2
        assert {row.invariant for row in rows} == {"concurrency_policy_dependency_inversion"}


def test_concurrency_cannot_redeclare_tenant_resource_or_priority_policy_semantics() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(
            root,
            "noetrium_platform/foundation/kernel/concurrency/runtime/runtime.py",
            "def configure(tenant_id, resource_id):\n"
            "    priority_aging_seconds = 1.0\n"
            "    return tenant_id, resource_id, priority_aging_seconds\n",
        )
        rows = audit_concurrency_boundary_invariants(root)
        assert rows
        assert {row.invariant for row in rows} == {"concurrency_policy_ownership_violation"}


def test_policy_runtime_may_consume_internal_scheduling_api() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(
            root,
            "noetrium_platform/research/execution/policy/runtime/authority.py",
            "from noetrium_platform.research.execution.policy.scheduling.api import AdmissionSchedulingPolicyPort\n",
        )
        assert audit_concurrency_boundary_invariants(root) == []


def test_internal_scheduling_facet_cannot_depend_on_policy_state() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(
            root,
            "noetrium_platform/research/execution/policy/scheduling/runtime/policy.py",
            "from noetrium_platform.research.execution.policy.api import AdmissionBudget\n",
        )
        rows = audit_concurrency_boundary_invariants(root)
        assert len(rows) == 1
        assert rows[0].invariant == "policy_scheduling_state_dependency"
