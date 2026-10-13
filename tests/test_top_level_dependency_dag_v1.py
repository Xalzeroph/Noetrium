from pathlib import Path
import ast
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "noetrium_platform"

SYSTEM_ROOTS = {
    "artifact": "evidence/artifact",
    "data": "evidence/data",
    "observability": "evidence/observability",
    "environment": "capabilities/environment",
    "model": "capabilities/model",
    "participant": "capabilities/participant",
    "runtime": "infrastructure/lifecycle",
    "resource": "infrastructure/resources",
    "reliability": "infrastructure/reliability",
    "execution": "research/execution",
    "experimentation": "research/experimentation",
}

PREFIX_TO_SYSTEM = {
    "noetrium_platform." + rel.replace("/", "."): name
    for name, rel in SYSTEM_ROOTS.items()
}

def owner(module: str) -> str | None:
    matches = [(prefix, name) for prefix, name in PREFIX_TO_SYSTEM.items() if module == prefix or module.startswith(prefix + ".")]
    return max(matches, default=(None, None), key=lambda row: len(row[0] or ""))[1]

def imports(path: Path):
    tree=ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            for alias in node.names: yield alias.name

def test_major_domain_dependency_graph_is_acyclic() -> None:
    graph=defaultdict(set)
    for path in PLATFORM.rglob("*.py"):
        rel=path.relative_to(ROOT).with_suffix("")
        parts=list(rel.parts)
        if parts[-1]=="__init__": parts.pop()
        source=owner(".".join(parts))
        if source is None: continue
        for target_module in imports(path):
            target=owner(target_module)
            if target is not None and target != source:
                graph[source].add(target)
    state={}
    stack=[]
    def visit(node):
        state[node]=1; stack.append(node)
        for target in sorted(graph[node]):
            if state.get(target)==1:
                i=stack.index(target)
                raise AssertionError("top-level dependency cycle: " + " -> ".join(stack[i:]+[target]))
            if state.get(target,0)==0: visit(target)
        stack.pop(); state[node]=2
    for node in sorted(set(graph)|{x for rows in graph.values() for x in rows}):
        if state.get(node,0)==0: visit(node)
