from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
PARTICIPANT = ROOT / "noetrium_platform" / "capabilities" / "participant"


def test_participant_domain_never_depends_on_execution_implementation() -> None:
    violations = []
    for path in PARTICIPANT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
                "noetrium_platform.research.execution"
            ):
                violations.append((str(path.relative_to(ROOT)), node.lineno, node.module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("noetrium_platform.research.execution"):
                        violations.append((str(path.relative_to(ROOT)), node.lineno, alias.name))
    assert violations == []
