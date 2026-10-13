from noetrium_platform.foundation.kernel.structure import GraphTrigger,GraphTriggerKind
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import execution_vertex,execution_flow,execution_graph,ResearchGraphNodeResult,ResearchGraphNodeState,ResearchGraphFailureProvenance
from noetrium_platform.composition.research_graph_frontier import ResearchGraphDependencyFrontier

def _d(x): return canonical_digest({'x':x})
def _result(x,state):
 kw={}
 if state is ResearchGraphNodeState.FAILED:
  kw=dict(failure_type='X',failure_message='x',failure_provenance=ResearchGraphFailureProvenance('tests.X',_d('f'),'x'))
 return ResearchGraphNodeResult(x,_d(x),state,**kw)
def _plan(kind,quorum=None):
 vs=tuple(execution_vertex(x,_d(x)) for x in ('a','b','c','z'))
 rel=execution_flow(('a','b','c'),('z',),trigger=GraphTrigger(kind,quorum))
 return execution_graph('g',_d('r'),vs,(rel,))
def test_any_releases_after_one_success_despite_other_failure():
 p=_plan(GraphTriggerKind.ANY); f=ResearchGraphDependencyFrontier(p,selected_node_ids=('a','b','c','z'),terminal_results={})
 assert f.ready_node_ids({'a','b','c','z'})==('a','b','c')
 f.consume_ready('a'); f.record_terminal(_result('a',ResearchGraphNodeState.FAILED)); assert 'z' not in f.ready_node_ids({'b','c','z'})
 f.consume_ready('b'); f.record_terminal(_result('b',ResearchGraphNodeState.SUCCEEDED)); assert 'z' in f.ready_node_ids({'c','z'})
def test_quorum_blocks_only_when_threshold_becomes_impossible():
 p=_plan(GraphTriggerKind.QUORUM,2); f=ResearchGraphDependencyFrontier(p,selected_node_ids=('a','b','c','z'),terminal_results={})
 for x in ('a','b'):
  f.consume_ready(x); f.record_terminal(_result(x,ResearchGraphNodeState.FAILED))
 assert f.blocked_nodes({'c','z'}) == (('z',('a','b')),)
def test_trigger_refresh_never_requeues_in_flight_source():
 p=_plan(GraphTriggerKind.ANY); f=ResearchGraphDependencyFrontier(p,selected_node_ids=('a','b','c','z'),terminal_results={})
 f.consume_ready('a'); f.consume_ready('b'); f.record_terminal(_result('a',ResearchGraphNodeState.SUCCEEDED))
 assert 'b' not in f.ready_node_ids({'b','c','z'})
 f.restore_ready('b'); assert 'b' in f.ready_node_ids({'b','c','z'})

def test_100_by_100_quorum_hyperedge_releases_all_targets_exactly_at_threshold():
 sources=tuple(f's{i:03d}' for i in range(100)); targets=tuple(f't{i:03d}' for i in range(100)); ids=sources+targets
 vs=tuple(execution_vertex(x,_d(x)) for x in ids)
 rel=execution_flow(sources,targets,trigger=GraphTrigger(GraphTriggerKind.QUORUM,51))
 p=execution_graph('hyper-100x100',_d('hyper-rev'),vs,(rel,)); f=ResearchGraphDependencyFrontier(p,selected_node_ids=ids,terminal_results={}); pending=set(ids)
 assert f.ready_node_ids(pending)==sources
 for x in sources[:50]:
  f.consume_ready(x); pending.remove(x); f.record_terminal(_result(x,ResearchGraphNodeState.SUCCEEDED))
 assert not (set(targets)&set(f.ready_node_ids(pending)))
 x=sources[50]; f.consume_ready(x); pending.remove(x); f.record_terminal(_result(x,ResearchGraphNodeState.SUCCEEDED))
 assert set(targets)<=set(f.ready_node_ids(pending))

def test_quorum_result_is_completion_order_invariant():
 sources=tuple(f'q{i}' for i in range(8)); target='z'; ids=sources+(target,); vs=tuple(execution_vertex(x,_d(x)) for x in ids)
 p=execution_graph('order-invariant',_d('order-rev'),vs,(execution_flow(sources,target,trigger=GraphTrigger(GraphTriggerKind.QUORUM,4)),))
 outcomes={sources[i]:(ResearchGraphNodeState.SUCCEEDED if i in {0,2,5,7} else ResearchGraphNodeState.FAILED) for i in range(8)}
 observations=[]
 for order in (sources,tuple(reversed(sources)),(sources[2],sources[7],sources[0],sources[5],sources[1],sources[3],sources[4],sources[6])):
  f=ResearchGraphDependencyFrontier(p,selected_node_ids=ids,terminal_results={}); pending=set(ids)
  for x in order:
   f.consume_ready(x);pending.remove(x);f.record_terminal(_result(x,outcomes[x]))
  observations.append((f.ready_node_ids(pending),f.blocked_nodes(pending)))
 assert observations[0]==observations[1]==observations[2]==((target,),())



def test_blocked_dependency_delta_is_drained_once_and_causally_exact():
    plan = _plan(GraphTriggerKind.QUORUM, 2)
    frontier = ResearchGraphDependencyFrontier(
        plan, selected_node_ids=("a", "b", "c", "z"),
        terminal_results={},
    )
    pending = {"a", "b", "c", "z"}
    frontier.consume_ready("a")
    pending.remove("a")
    frontier.record_terminal(_result("a", ResearchGraphNodeState.FAILED))
    assert frontier.drain_newly_blocked(pending) == ()

    frontier.consume_ready("b")
    pending.remove("b")
    frontier.record_terminal(_result("b", ResearchGraphNodeState.FAILED))
    assert frontier.drain_newly_blocked(pending) == (("z", ("a", "b")),)
    assert frontier.drain_newly_blocked(pending) == ()
    assert frontier.blocked_nodes(pending) == (("z", ("a", "b")),)

    pending.remove("z")
    frontier.record_terminal(ResearchGraphNodeResult("z", _d("z"), ResearchGraphNodeState.BLOCKED, blocked_by_node_ids=("a", "b")))
    assert frontier.drain_newly_blocked(pending) == ()
