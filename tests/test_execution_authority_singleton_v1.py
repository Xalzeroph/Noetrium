from __future__ import annotations

import ast
from pathlib import Path


_CANONICAL_DEFINITIONS = {
    "UniversalMethodMachine": "noetrium_platform/research/execution/workflow/runtime/method_machine.py",
    "ResearchGraphScheduler": "noetrium_platform/composition/research_graph.py",
}
_ALLOWED_CALLERS = {
    "UniversalMethodMachine": {
        "noetrium_platform/composition/research_os_runtime.py",
    },
    "ResearchGraphScheduler": {
        "noetrium_platform/composition/research_campaign.py",
        "noetrium_platform/composition/research_os_graph.py",
    },
    "MethodRunResult": {
        "noetrium_platform/research/execution/workflow/runtime/method_machine.py",
    },
}


def _called_name(node: ast.Call) -> str | None:
    target = node.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def test_core_execution_authorities_have_one_definition_and_one_call_path() -> None:
    root = Path(__file__).resolve().parents[1]
    definitions = {name: [] for name in _CANONICAL_DEFINITIONS}
    callers = {name: [] for name in _ALLOWED_CALLERS}

    for path in sorted((root / "noetrium_platform").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in definitions:
                definitions[node.name].append(relative)
            if isinstance(node, ast.Call):
                name = _called_name(node)
                if name in callers:
                    callers[name].append(relative)

    assert definitions == {
        name: [path]
        for name, path in _CANONICAL_DEFINITIONS.items()
    }
    assert {
        name: set(paths)
        for name, paths in callers.items()
    } == _ALLOWED_CALLERS
