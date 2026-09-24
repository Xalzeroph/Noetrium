from __future__ import annotations

import ast
from pathlib import Path


_CANONICAL_DEFINITIONS = {
    "UniversalMethodMachine": "noetrium_platform/research/execution/workflow/runtime/method_machine.py",
    "ResearchGraphScheduler": "noetrium_platform/composition/research_graph.py",
    "ResearchOSExperimentRuntimeBindingAuthority": (
        "noetrium_platform/composition/"
        "research_os_experiment_runtime_binding.py"
    ),
}
_FORBIDDEN_CLASS_NAMES = {
    "UniversalExperimentKernel",
    "ExperimentRuntime",
    "DecisionCycleRuntime",
    "RunRuntime",
    "RunCycleExecutor",
    "RunSession",
    "ExperimentTrialCycleExecutor",
    "TrialExperimentProgramBinding",
}
_FORBIDDEN_FUNCTION_NAMES = {
    "build_experiment_runtime",
    "build_experiment_runtime_components",
    "compile_trial_experiment_program",
}

_ALLOWED_CALLERS = {
    "UniversalMethodMachine": {
        "noetrium_platform/composition/research_os_runtime.py",
    },
    "ResearchGraphScheduler": {
        "noetrium_platform/composition/research_os_graph.py",
    },
    "MethodRunResult": {
        "noetrium_platform/research/execution/workflow/runtime/method_machine.py",
    },
    "build_experiment_runtime": set(),
    "ExperimentRuntime": set(),
    "DecisionCycleRuntime": set(),
    "RunRuntime": set(),
    "ExperimentTrialCycleExecutor": set(),
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
    forbidden_definitions = {name: [] for name in _FORBIDDEN_CLASS_NAMES}
    forbidden_functions = {name: [] for name in _FORBIDDEN_FUNCTION_NAMES}
    callers = {name: [] for name in _ALLOWED_CALLERS}

    for path in sorted((root / "noetrium_platform").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in definitions:
                definitions[node.name].append(relative)
            if isinstance(node, ast.ClassDef) and node.name in forbidden_definitions:
                forbidden_definitions[node.name].append(relative)
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in forbidden_functions
            ):
                forbidden_functions[node.name].append(relative)
            if isinstance(node, ast.Call):
                name = _called_name(node)
                if name in callers:
                    callers[name].append(relative)

    assert definitions == {
        name: [path]
        for name, path in _CANONICAL_DEFINITIONS.items()
    }
    assert all(not paths for paths in forbidden_definitions.values()), forbidden_definitions
    assert all(not paths for paths in forbidden_functions.values()), forbidden_functions
    assert {
        name: set(paths)
        for name, paths in callers.items()
    } == _ALLOWED_CALLERS
