from noetrium_platform.foundation.kernel.structure import (
    boundary_unit, endpoint_child_id, endpoint_unit, port_unit,
    relation_unit, structure_unit, type_unit,
)
import pytest
from noetrium_platform.foundation.kernel.structure import NoetriumUnit,NoetriumUnit,NoetriumUnit,NoetriumUnit
from noetrium_platform.foundation.kernel.unit_algebra import unit_compose,unit_parallel,unit_substitute

def _g(i,ins=(),outs=()):
 t=type_unit('test.value'); return structure_unit(i,boundary=boundary_unit(inputs=tuple(port_unit(x,t) for x in ins),outputs=tuple(port_unit(x,t) for x in outs)))
def test_parallel_adds_no_dependencies():
 g=unit_parallel('p',_g('a'),_g('b')); assert g.relations==()
def test_compose_is_associative_in_observable_sequence_shape():
 a,b,c=_g('a',outs=('x',)),_g('b',ins=('x',),outs=('y',)),_g('c',ins=('y',))
 whole=unit_compose('abc',a,b,c); assert len(whole.relations)==2
 assert {(endpoint_child_id(r.units('source')[0]), endpoint_child_id(r.units('target')[0])) for r in whole.relations}=={('a','b'),('b','c')}
def test_substitution_requires_boundary_refinement():
 a=_g('a',outs=('x',)); root=unit_parallel('root',a)
 assert unit_substitute(root,'a',_g('a',outs=('x',))).member('a').unit_id=='a'
 with pytest.raises(ValueError): unit_substitute(root,'a',_g('a'))


def test_semantic_identity_is_alpha_invariant_for_local_graph_and_relation_ids():
 from noetrium_platform.foundation.kernel.structure import NoetriumUnit,NoetriumUnit
 t=type_unit('test.value')
 def make(root,left,right,relation):
  a=structure_unit(left,boundary=boundary_unit(outputs=(port_unit('out',t),)))
  b=structure_unit(right,boundary=boundary_unit(inputs=(port_unit('in',t),)))
  return structure_unit(root,members=(a,b),relations=(relation_unit((endpoint_unit(left,'out'),),(endpoint_unit(right,'in'),),relation),))
 left=make('root-a','left-a','right-a','flow-a'); right=make('root-b','x','y','flow-b')
 assert left.semantic_digest == right.semantic_digest
 assert left.unit_digest != right.unit_digest


def test_compose_is_closed_over_observable_boundary():
    a,b,c=_g('a',ins=('i',),outs=('x',)),_g('b',ins=('x',),outs=('y',)),_g('c',ins=('y',),outs=('o',))
    ab=unit_compose('ab',a,b)
    assert tuple(x.unit_id for x in ab.boundary.units('input'))==('i',)
    assert tuple(x.unit_id for x in ab.boundary.units('output'))==('y',)
    abc=unit_compose('abc-nested',ab,c)
    assert tuple(x.unit_id for x in abc.boundary.units('input'))==('i',)
    assert tuple(x.unit_id for x in abc.boundary.units('output'))==('o',)
