from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, imports, violation


def audit_model_dependency_invariants(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    model_os = root / "noetrium_platform" / "capabilities" / "model" / "serving"
    if model_os.exists():
        for path in sorted(model_os.glob("*.py")):
            if path.name != "__init__.py":
                rows.append(violation(
                    root, path, "model_serving_layer_layout", 1,
                    f"Model Serving implementation module {path.name} is flat at subsystem root; place contracts in api, behavior in runtime, backends in providers, and wiring in composition",
                ))
        inventory_owner = model_os / "api" / "inventory.py"
        canonical_inventory_classes = {"CPUInventory", "GPUInventory", "HostInventory", "MemoryInventory", "MountInventory", "RuntimeInventory", "HostLimits", "GPUFabricLink"}
        forbidden_parallel_planners = {"PlacementPlanner", "TopologyPlanner", "TopologyInventory", "TargetHostInventory"}
        for path in sorted(model_os.rglob("*.py")):
            tree = source_tree(path)
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                if path != inventory_owner and node.name in canonical_inventory_classes:
                    rows.append(violation(root, path, "model_os_inventory_authority", node.lineno, f"host inventory class {node.name} is defined outside serving/api/inventory.py"))
                if node.name in forbidden_parallel_planners or node.name.endswith(("InventoryV1", "InventoryV2")):
                    rows.append(violation(root, path, "model_os_inventory_authority", node.lineno, f"parallel/legacy model OS inventory or planner is forbidden: {node.name}"))

    runtime_manager = root / "noetrium_platform" / "research" / "execution" / "runtime" / "manager"
    forbidden = "noetrium_platform.capabilities.model.serving.api.host_verification"
    if runtime_manager.exists():
        for path in sorted(runtime_manager.rglob("*.py")):
            for module, line in imports(path):
                if module == forbidden or module.startswith(forbidden + "."):
                    rows.append(violation(root, path, "runtime_manager_host_verification_boundary", line, f"runtime manager imports host-verification implementation {module}; use HostRuntimeVerificationPort and composition adapter"))
    return rows


__all__ = ["audit_model_dependency_invariants"]
