from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
RESOURCE = ROOT / "noetrium_platform" / "infrastructure" / "resources"


def test_resource_authority_never_depends_on_runtime_lifecycle() -> None:
    violations = []
    for path in RESOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            elif isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            for name in names:
                if name.startswith("noetrium_platform.infrastructure.lifecycle"):
                    violations.append((str(path.relative_to(ROOT)), node.lineno, name))
    assert violations == []
