from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, violation


def audit_prompt_api_invariants(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    prompt = root / "noetrium_platform" / "capabilities" / "model" / "request" / "prompt" / "runtime"
    runtime_manager = root / "noetrium_platform" / "research" / "execution" / "runtime" / "manager"
    forbidden_prompt_storage_modules = {
        "noetrium_platform.capabilities.model.request.prompt.runtime.promotion_store",
        "noetrium_platform.capabilities.model.request.prompt.runtime.active_pointer",
        "noetrium_platform.capabilities.model.request.prompt.runtime.generation_store",
        "noetrium_platform.capabilities.model.request.prompt.runtime.promotion_record_store",
    }
    for path in runtime_manager.glob("*.py"):
        tree = source_tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "") in forbidden_prompt_storage_modules:
                rows.append(violation(
                    root, path, "prompt_verification_storage_encapsulation", node.lineno,
                    f"runtime manager imports Prompt OS storage implementation {node.module}; depend on noetrium_platform.capabilities.model.request.prompt.api",
                ))
            if isinstance(node, ast.Attribute) and node.attr in {"pointer", "records", "generation_store"}:
                rows.append(violation(
                    root, path, "prompt_verification_storage_encapsulation", node.lineno,
                    f"runtime manager reaches Prompt OS internal authority {node.attr}; consume ActivePromptEvidenceReadPort",
                ))
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("noetrium_platform.capabilities.model.request.prompt.runtime"):
                rows.append(violation(
                    root, path, "prompt_external_api_boundary", node.lineno,
                    f"runtime manager imports Prompt OS implementation {node.module}; depend on prompt_api",
                ))

    prompt_api = root / "noetrium_platform" / "capabilities" / "model" / "request" / "prompt" / "api"
    if prompt_api.exists():
        for api_path in sorted(prompt_api.rglob("*.py")):
            api_tree = source_tree(api_path)
            for node in ast.walk(api_tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("noetrium_platform.capabilities.model.request.prompt.runtime"):
                    rows.append(violation(
                        root, api_path, "prompt_api_dependency_firewall", node.lineno,
                        f"prompt API imports Prompt OS implementation {node.module}",
                    ))

    legacy_api = prompt / "verification_api.py"
    if legacy_api.exists():
        rows.append(violation(
            root, legacy_api, "prompt_external_api_boundary", 1,
            "prompt verification cross-system ABI must live in noetrium_platform.capabilities.model.request.prompt.api",
        ))
    return rows


__all__ = ["audit_prompt_api_invariants"]
