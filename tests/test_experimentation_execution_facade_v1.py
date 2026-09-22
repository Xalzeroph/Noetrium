from pathlib import Path
import ast

ROOT=Path(__file__).resolve().parents[1]
EXPERIMENTATION=ROOT/"noetrium_platform"/"research"/"experimentation"
ALLOWED="noetrium_platform.research.execution.api"

def test_experimentation_consumes_only_execution_parent_facade() -> None:
    violations=[]
    for path in EXPERIMENTATION.rglob("*.py"):
        tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
        for node in ast.walk(tree):
            names=[]
            if isinstance(node,ast.ImportFrom) and node.module:
                names.append(node.module)
            elif isinstance(node,ast.Import):
                names.extend(alias.name for alias in node.names)
            for name in names:
                if name.startswith("noetrium_platform.research.execution") and not (
                    name==ALLOWED or name.startswith(ALLOWED+".")
                ):
                    violations.append((str(path.relative_to(ROOT)),node.lineno,name))
    assert violations==[]
