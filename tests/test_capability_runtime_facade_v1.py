from pathlib import Path
import ast

ROOT=Path(__file__).resolve().parents[1]
ALLOWED="noetrium_platform.infrastructure.lifecycle.api"

def _violations(base: Path):
    rows=[]
    for path in base.rglob("*.py"):
        tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
        for node in ast.walk(tree):
            names=[]
            if isinstance(node,ast.ImportFrom) and node.module: names.append(node.module)
            elif isinstance(node,ast.Import): names.extend(alias.name for alias in node.names)
            for name in names:
                if name.startswith("noetrium_platform.infrastructure.lifecycle") and not (
                    name==ALLOWED or name.startswith(ALLOWED+".")
                ):
                    rows.append((str(path.relative_to(ROOT)),node.lineno,name))
    return rows

def test_environment_consumes_only_runtime_parent_facade() -> None:
    assert _violations(ROOT/"noetrium_platform"/"capabilities"/"environment")==[]

def test_model_consumes_only_runtime_parent_facade() -> None:
    assert _violations(ROOT/"noetrium_platform"/"capabilities"/"model")==[]
