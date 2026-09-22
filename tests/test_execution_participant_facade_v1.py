from pathlib import Path
import ast

ROOT=Path(__file__).resolve().parents[1]
EXECUTION=ROOT/"noetrium_platform"/"research"/"execution"
ALLOWED="noetrium_platform.capabilities.participant.api"

def test_execution_consumes_only_participant_parent_facade() -> None:
    violations=[]
    for path in EXECUTION.rglob("*.py"):
        tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
        for node in ast.walk(tree):
            names=[]
            if isinstance(node,ast.ImportFrom) and node.module:
                names.append(node.module)
            elif isinstance(node,ast.Import):
                names.extend(alias.name for alias in node.names)
            for name in names:
                if name.startswith("noetrium_platform.capabilities.participant") and not (
                    name==ALLOWED or name.startswith(ALLOWED+".")
                ):
                    violations.append((str(path.relative_to(ROOT)),node.lineno,name))
    assert violations==[]
