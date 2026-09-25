from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path

from .source_index import source_nodes, source_text, source_tree

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .import_graph import scan_imports

IO_NAMES={"open","read_text","write_text","read_bytes","write_bytes","fsync","connect","execute","executemany","commit"}
SER_NAMES={"dumps","loads","dump","load"}
LOCK_NAMES={"Lock","RLock","acquire","release"}

@dataclass(frozen=True, slots=True)
class ModuleOptimizationProfile:
    module: str
    path: str
    import_fan_in: int
    import_fan_out: int
    io_sites: int
    serialization_sites: int
    lock_sites: int
    self_mutation_sites: int
    exception_handlers: int
    long_functions: int
    risk_score: int
    reason_codes: tuple[str,...]

@dataclass(frozen=True, slots=True)
class OptimizationReport:
    source_root: str
    modules: tuple[ModuleOptimizationProfile,...]
    report_sha256: str


def _module_for(root:Path,path:Path)->str:
    return ".".join(path.relative_to(root).with_suffix("").parts).replace(".__init__","")

def _called_name(node:ast.Call)->str|None:
    f=node.func
    if isinstance(f,ast.Name): return f.id
    if isinstance(f,ast.Attribute): return f.attr
    return None

def _self_mutation(node:ast.AST)->bool:
    targets=[]
    if isinstance(node,(ast.Assign,ast.AnnAssign,ast.AugAssign)):
        targets = node.targets if isinstance(node,ast.Assign) else [node.target]
    for t in targets:
        if isinstance(t,ast.Attribute) and isinstance(t.value,ast.Name) and t.value.id=="self": return True
        if isinstance(t,ast.Subscript) and isinstance(t.value,ast.Attribute) and isinstance(t.value.value,ast.Name) and t.value.value.id=="self": return True
    return False

def analyze_optimization_risks(root:Path,package_roots:tuple[str,...]=( "noetrium_platform","projects"))->tuple[ModuleOptimizationProfile,...]:
    edges=scan_imports(root); fan_in={}; fan_out={}
    for e in edges:
        fan_out[e.source_module]=fan_out.get(e.source_module,0)+1
        fan_in[e.target_module]=fan_in.get(e.target_module,0)+1
    rows=[]
    for pkg in package_roots:
        base=root/pkg
        if not base.exists(): continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts: continue
            text=source_text(path); tree=source_tree(path); module=_module_for(root,path)
            nodes=source_nodes(path); calls=[n for n in nodes if isinstance(n,ast.Call)]
            io=sum((_called_name(n) in IO_NAMES) for n in calls)
            ser=sum((_called_name(n) in SER_NAMES) for n in calls)
            lock=sum((_called_name(n) in LOCK_NAMES) for n in calls)
            muts=sum(_self_mutation(n) for n in nodes)
            handlers=sum(isinstance(n,ast.ExceptHandler) for n in nodes)
            funcs=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
            long=sum((getattr(n,"end_lineno",n.lineno)-n.lineno+1)>50 for n in funcs)
            fi=fan_in.get(module,0); fo=fan_out.get(module,0)
            score=fi*4+fo*3+io*8+ser*4+lock*12+muts*5+handlers*8+long*20
            reasons=[]
            if fi>=8: reasons.append("HIGH_FAN_IN")
            if fo>=10: reasons.append("HIGH_FAN_OUT")
            if io>=6: reasons.append("IO_CONCENTRATION")
            if ser>=8: reasons.append("SERIALIZATION_CONCENTRATION")
            if lock>=3: reasons.append("LOCK_CONTENTION_RISK")
            if muts>=8: reasons.append("STATE_MUTATION_CONCENTRATION")
            if handlers>=4: reasons.append("FAILURE_BRANCH_CONCENTRATION")
            if long: reasons.append("LONG_FUNCTION")
            rows.append(ModuleOptimizationProfile(module,path.relative_to(root).as_posix(),fi,fo,io,ser,lock,muts,handlers,long,score,tuple(reasons)))
    return tuple(sorted(rows,key=lambda x:(-x.risk_score,x.module)))

def build_optimization_report(root:Path,*,limit:int=40)->OptimizationReport:
    modules=analyze_optimization_risks(root)[:limit]
    base={"source_root":str(root.resolve()),"modules":[asdict(x) for x in modules]}
    identity={"modules":base["modules"]}
    digest=canonical_digest(identity)
    return OptimizationReport(base["source_root"],modules,digest)
