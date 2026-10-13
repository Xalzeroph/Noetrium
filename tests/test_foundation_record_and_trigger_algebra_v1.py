from noetrium_platform.foundation.kernel.structure import endpoint_unit, relation_trigger, relation_unit, structure_unit
from noetrium_platform.foundation.kernel.structure import NoetriumUnit,GraphProgressKind,NoetriumUnit,GraphTrigger,GraphTriggerKind
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.record import GraphSubjectFacet,GraphSubjectRef,RecordRequirement,RecordRole,record_has_role,record_unit

def test_record_roles_are_nonexclusive_and_bind_exact_graph_subject():
 s=GraphSubjectRef(canonical_digest({'g':'x'}),'effect:collect',GraphSubjectFacet.EFFECT)
 r=record_unit('minecraft.inventory.observed',frozenset({RecordRole.JOURNAL,RecordRole.EVIDENCE}),s,{'oak_log':4})
 assert record_has_role(r,RecordRole.JOURNAL) and record_has_role(r,RecordRole.EVIDENCE)
 assert RecordRequirement('inventory',('minecraft.inventory.observed',)).satisfied_by(r)

def test_relation_trigger_algebra_all_any_quorum_and_progress():
 src=tuple(endpoint_unit(f's{i}',None) for i in range(3)); dst=(endpoint_unit('t',None),)
 q=relation_unit(src,dst,'flow',trigger=GraphTrigger(GraphTriggerKind.QUORUM,2),progress=GraphProgressKind.EXTERNAL)
 assert not relation_trigger(q).satisfied(satisfied_sources=1,source_count=3)
 assert relation_trigger(q).satisfied(satisfied_sources=2,source_count=3)
 assert GraphTrigger(GraphTriggerKind.ANY).satisfied(satisfied_sources=1,source_count=3)
 assert not GraphTrigger().satisfied(satisfied_sources=2,source_count=3)

def test_ready_frontier_is_derived_from_trigger_not_parallelism_knob():
 from noetrium_platform.foundation.kernel.structure import NoetriumUnit,structure_ready_targets
 a,b,c=(structure_unit(x) for x in ('a','b','c'))
 r=relation_unit((endpoint_unit('a',None),endpoint_unit('b',None)),(endpoint_unit('c',None),),'flow',trigger=GraphTrigger(GraphTriggerKind.ALL))
 g=structure_unit('g',members=(a,b,c),relations=(r,))
 assert structure_ready_targets(g,satisfied_members=frozenset({'a'})) == ('b',)
 assert structure_ready_targets(g,satisfied_members=frozenset({'a','b'})) == ('c',)

def test_execution_cycle_requires_explicit_progress_source():
 from noetrium_platform.foundation.kernel.structure import NoetriumUnit,validate_execution_progress
 import pytest
 a,b=(structure_unit(x) for x in ('a','b'))
 r1=relation_unit((endpoint_unit('a',None),),(endpoint_unit('b',None),),'flow')
 r2=relation_unit((endpoint_unit('b',None),),(endpoint_unit('a',None),),'flow')
 with pytest.raises(ValueError,match='progress source'): validate_execution_progress(structure_unit('g',members=(a,b),relations=(r1,r2)))
 r2=relation_unit((endpoint_unit('b',None),),(endpoint_unit('a',None),),'flow',progress=GraphProgressKind.EXTERNAL)
 validate_execution_progress(structure_unit('g',members=(a,b),relations=(r1,r2)))

def test_execution_graph_preserves_hyperflow_trigger():
 from noetrium_platform.foundation.kernel.kernel import canonical_digest
 from noetrium_platform.research.execution.graph.api import execution_vertex,execution_flow,execution_graph,execution_dependency_source_node_ids,execution_dependency_trigger
 a,b,c=(execution_vertex(x,canonical_digest({'x':x})) for x in ('a','b','c'))
 rel=execution_flow(('a','b'),('c',),trigger=GraphTrigger(GraphTriggerKind.ANY))
 g=execution_graph('e',canonical_digest({'r':1}),(a,b,c),(rel,))
 assert len(execution_dependency_source_node_ids(g.relations[0]))==2
 assert execution_dependency_trigger(g.relations[0]).kind is GraphTriggerKind.ANY

def test_progress_marked_cycle_is_valid_semantics_but_not_a_dag_schedule():
 from noetrium_platform.foundation.kernel.structure import NoetriumUnit,structure_topological_order,validate_execution_progress
 a=structure_unit('a'); b=structure_unit('b')
 rels=(relation_unit((endpoint_unit('a',None),),(endpoint_unit('b',None),),'flow'),relation_unit((endpoint_unit('b',None),),(endpoint_unit('a',None),),'flow',progress=GraphProgressKind.STATE))
 g=structure_unit('loop',members=(a,b),relations=rels)
 validate_execution_progress(g,frozenset({'flow'}))
 import pytest
 with pytest.raises(ValueError): structure_topological_order(g,('flow',))
