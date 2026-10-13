from __future__ import annotations
import ast
from pathlib import Path
from .source_index import source_nodes
from .source_scan import SourceInvariantViolation,is_transient_source_path,violation

_FORBIDDEN_CLASSES=frozenset({'CompiledResearchPlan','CompiledExperimentShardPlan','ModelReplicaShardPlan','StudyExecutionPlan','ExperimentCompilation','RuntimePlan','TableProgram','MethodToMachineGraphTransform','CausalGraph','MethodRuntimeBindingPlan','ResearchPlanDiff','ArtifactRecord','DeploymentQualificationEvidenceRecord','_MethodModelInvocationPlan','BindingPlan','ExactCapacityPlanner','ExactCapacityPlan','GpuPlacementPolicyPort','ExactFabricPlacementPolicy','LifecycleSpec','LifecycleExecutor','LifecycleComponent'})
_FORBIDDEN_NAMES=frozenset({'RESOURCE_RELEASE_BEFORE_RELATION','RESOURCE_PRECEDES_RELATION','RESOURCE_STAGE_TRAIT','RESOURCE_LIFECYCLE_TRAIT','endpoint_candidate_count','max_parallel','dispatch_parallelism'})
FORBIDDEN_LEGACY_MARKERS=('compatibility fallback only','Preserve compatibility with environment factories that predate','runtime_tuning_revision: str = "legacy"','resource.lifecycle.precedes','resource.lifecycle.stage','managed_resource_lifecycle_graph','apply_deterministic_rewrite','resource.placement','resource.binding','resource.inventory','resource.supply')

def audit_ultimate_kernel_invariants(root:Path)->list[SourceInvariantViolation]:
 root=Path(root).resolve(); rows=[]; package=root/'noetrium_platform'
 for path in sorted(package.rglob('*.py')):
  if is_transient_source_path(path): continue
  rel=path.relative_to(root).as_posix()
  if rel.endswith('/ultimate_kernel_invariants.py'): continue
  text=path.read_text(encoding='utf-8')
  for token in FORBIDDEN_LEGACY_MARKERS:
   if token in text:
    rows.append(violation(root,path,'legacy_compatibility_seam',text[:text.index(token)].count('\n')+1,f'legacy compatibility seam is forbidden: {token}'))
  for node in source_nodes(path):
   if isinstance(node,ast.ClassDef) and node.name in _FORBIDDEN_CLASSES:
    rows.append(violation(root,path,'duplicate_structural_carrier',node.lineno,f'{node.name} duplicates the canonical NoetriumUnit/Rewrite kernel'))
   if isinstance(node,ast.Name) and node.id in _FORBIDDEN_NAMES:
    rows.append(violation(root,path,'duplicate_lifecycle_direction',node.lineno,f'{node.id} duplicates inverse order derivable from resource lifecycle requirements'))
   if isinstance(node,(ast.Import,ast.ImportFrom)):
    names=[]
    if isinstance(node,ast.Import): names=[x.name for x in node.names]
    else: names=[node.module or '']
    if any(x=='noetrium_platform.foundation.kernel.graph_transform' or x.startswith('noetrium_platform.foundation.kernel.graph_transform.') for x in names):
     rows.append(violation(root,path,'duplicate_rewrite_algebra',node.lineno,'GraphTransform is forbidden; deterministic transforms are GraphRewrite specializations'))
 return rows

__all__=['FORBIDDEN_LEGACY_MARKERS','audit_ultimate_kernel_invariants']
