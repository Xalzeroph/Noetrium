from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "noetrium_platform" / "infrastructure" / "lifecycle"

FORBIDDEN = (
    "noetrium_platform.evidence.observability",
    "noetrium_platform.infrastructure.reliability.recovery",
)

def test_runtime_lifecycle_does_not_depend_on_observability_or_recovery_policy() -> None:
    violations = []
    for path in RUNTIME.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            elif isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            for name in names:
                if name.startswith(FORBIDDEN):
                    violations.append((str(path.relative_to(ROOT)), node.lineno, name))
    assert violations == []
