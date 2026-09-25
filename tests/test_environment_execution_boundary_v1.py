from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = ROOT / "noetrium_platform" / "capabilities" / "environment"


def test_environment_authority_never_depends_on_execution_domain() -> None:
    violations = []
    for path in ENVIRONMENT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            elif isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            for name in names:
                if name.startswith("noetrium_platform.research.execution"):
                    violations.append((str(path.relative_to(ROOT)), node.lineno, name))
    assert violations == []
