from __future__ import annotations

from pathlib import Path
import tempfile

from noetrium_platform.foundation.governance.architecture.concurrency_boundary_invariants import (
    audit_concurrency_boundary_invariants,
)
from noetrium_platform.foundation.governance.system_registry.api import system_catalog
from noetrium_platform.research.execution.admission.api import boundary as admission_boundary


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_admission_leaf_metadata_is_not_direct_authority_truth() -> None:
    descriptor = next(
        item for item in system_catalog() if item.identity.key == "execution/admission"
    )
    assert admission_boundary.OWNS == descriptor.owns
    assert admission_boundary.CONTRACT.owns == descriptor.owns
    # Leaf metadata remains a generated topology projection for compatibility.
    assert admission_boundary.AUTHORITY == "admission_decision"
    assert admission_boundary.CONTRACT.authority_id == "admission_decision"
    # The registry classification is the only authority truth.
    assert descriptor.authority_id is None
    assert descriptor.canonical_authority_key == "execution"


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


def test_concurrency_cannot_import_admission_or_scheduling_policy_systems() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(
            root,
            "noetrium_platform/foundation/kernel/concurrency/runtime/runtime.py",
            "from noetrium_platform.research.execution.admission.api import ExecutionAdmissionPort\n"
            "from noetrium_platform.research.execution.scheduling.api import ExecutionPriority\n",
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


def test_admission_may_use_scheduling_api_but_not_scheduling_runtime() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(
            root,
            "noetrium_platform/research/execution/admission/runtime/authority.py",
            "from noetrium_platform.research.execution.scheduling.api import AdmissionSchedulingPolicyPort\n",
        )
        assert audit_concurrency_boundary_invariants(root) == []
        _write(
            root,
            "noetrium_platform/research/execution/admission/runtime/bad.py",
            "from noetrium_platform.research.execution.scheduling.runtime import FairPrioritySchedulingPolicy\n",
        )
        rows = audit_concurrency_boundary_invariants(root)
        assert len(rows) == 1
        assert rows[0].invariant == "admission_scheduling_implementation_bypass"


def test_scheduling_cannot_depend_back_on_admission() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(
            root,
            "noetrium_platform/research/execution/scheduling/runtime/policy.py",
            "from noetrium_platform.research.execution.admission.api import AdmissionBudget\n",
        )
        rows = audit_concurrency_boundary_invariants(root)
        assert len(rows) == 1
        assert rows[0].invariant == "scheduling_admission_reverse_dependency"
