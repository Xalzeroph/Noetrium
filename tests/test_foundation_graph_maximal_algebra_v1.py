from noetrium_platform.foundation.kernel.structure import boundary_unit, endpoint_unit, port_unit, relation_unit, structure_unit, type_unit
from dataclasses import dataclass
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, NoetriumUnit, NoetriumUnit, NoetriumUnit, NoetriumUnit, NoetriumUnit
from noetrium_platform.foundation.kernel.unit_identity import UnitIdentityFacet, unit_identity
from noetrium_platform.foundation.kernel.unit_refinement import boundary_refines
from noetrium_platform.foundation.kernel.unit_rewrite import apply_unit_rewrite, rewrite_frontier


def test_relation_is_native_n_to_m_and_has_no_binary_compatibility_surface():
    r=relation_unit((endpoint_unit('a',None),endpoint_unit('b',None)),(endpoint_unit('c',None),endpoint_unit('d',None)),'research.join')
    assert len(r.units('source'))==2 and len(r.units('target'))==2
    assert not hasattr(r,'source') and not hasattr(r,'target')


def test_boundary_refinement_is_input_contravariant_output_covariant():
    any_t=type_unit('test.any'); narrow=type_unit('test.narrow',supertypes=('test.any',))
    required=boundary_unit(inputs=(port_unit('x',narrow),),outputs=(port_unit('y',any_t),))
    candidate=boundary_unit(inputs=(port_unit('x',any_t),),outputs=(port_unit('y',narrow),))
    assert boundary_refines(candidate,required)
    assert not boundary_refines(required,candidate)


@dataclass(frozen=True)
class Rewrite:
    rule_id='test.refine'; source_traits=frozenset({'test.source'})
    def rewrite(self,graph,*,context):
        return (structure_unit('b',traits=('test.source',),boundary=graph.boundary), structure_unit('b2',traits=('test.source',),boundary=graph.boundary))


def test_rewrite_is_non_destructive_and_saturates_with_hash_consing():
    g=structure_unit('a',traits=('test.source',))
    out=apply_unit_rewrite(Rewrite(),g)
    assert len(out)==1  # graph_id is not semantic identity; equivalent candidates hash-cons
    saturated=rewrite_frontier(g,(Rewrite(),),max_rounds=4)
    assert len(saturated)==1


@dataclass(frozen=True)
class Projection:
    facet=UnitIdentityFacet.REALIZATION; projection_id='test.model-realization.v1'
    def project(self,graph): return {'model':graph.parameters.get('model')}


def test_realization_identity_can_share_across_distinct_semantic_graphs():
    a=structure_unit('trial-a',traits=('test.trial',),parameters={'model':'qwen3-8b','seed':1})
    b=structure_unit('trial-b',traits=('test.trial',),parameters={'model':'qwen3-8b','seed':2})
    assert a.semantic_digest != b.semantic_digest
    assert unit_identity(a,Projection()) == unit_identity(b,Projection())

def test_alpha_identity_fallback_handles_symmetric_repeated_children():
    def make(root,a,b,rel):
        leaf1=structure_unit(a,traits=('same',)); leaf2=structure_unit(b,traits=('same',))
        return structure_unit(root,members=(leaf1,leaf2),relations=(relation_unit((endpoint_unit(a,None),),(endpoint_unit(b,None),),rel),))
    left=make('r1','a','b','x'); right=make('r2','u','v','y')
    assert left.semantic_digest==right.semantic_digest

def test_deep_recursive_unit_identity_is_deterministic():
    g=structure_unit('leaf',traits=('depth.leaf',))
    for depth in range(200):
        g=structure_unit(f'g{depth}',traits=('depth.wrapper',),members=(g,))
    assert len(g.semantic_digest)==64
    assert g.semantic_digest==g.semantic_digest
