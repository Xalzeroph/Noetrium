from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineKind,
    MachineStatus,
    canonical_digest,
)
from research.reproductions.agentsquare import (
    AGENTSQUARE_ALFWORLD_OPTIMIZATION_PROGRAM,
    AGENTSQUARE_FIDELITY,
    AgentSquareEvaluation,
    AgentSquareEvolutionProposal,
    AgentSquareModuleEvaluation,
    AgentSquareOptimizationBinding,
    agentsquare_alfworld_host,
    agentsquare_alfworld_initial_data,
    agentsquare_alfworld_instance_identity,
)


class _SearchModel:
    def __init__(self) -> None:
        self.evolve_calls = 0
        self.recombine_calls = 0
        self.predict_calls = 0

    @property
    def identity_digest(self) -> str:
        return canonical_digest({"fake": "agentsquare-search-model", "v": 1})

    def evolve(self, *, current_agent, module_archives):
        del module_archives
        self.evolve_calls += 1
        i = self.evolve_calls
        proposals = {
            "planning": {
                "name": f"plan-{i}",
                "thought": "planning mutation",
                "code": "class PlanningTest: pass",
            },
            "reasoning": {
                "name": f"reason-{i}",
                "thought": "reasoning mutation",
                "code": "class ReasoningTest: pass",
            },
            "tooluse": {
                "name": f"tool-{i}",
                "thought": "tool mutation",
                "code": "class TooluseTest: pass",
            },
            "memory": {
                "name": f"memory-{i}",
                "thought": "memory mutation",
                "code": "class MemoryTest: pass",
            },
        }
        candidates = []
        for key, proposal in proposals.items():
            row = dict(current_agent)
            row[key] = proposal["name"]
            candidates.append(row)
        return AgentSquareEvolutionProposal(
            module_proposals=proposals,
            candidate_agents=tuple(candidates),
            receipt={"iteration": i},
        )

    def recombine(self, *, current_agent, module_archives, tested_cases):
        del module_archives, tested_cases
        self.recombine_calls += 1
        i = self.recombine_calls
        rows = []
        for index in range(4):
            row = dict(current_agent)
            row["planning"] = f"recombined-plan-{i}-{index}"
            row["tooluse"] = "None"
            rows.append(row)
        return tuple(rows)

    def predict(self, *, module_archives, tested_cases, candidates):
        del module_archives, tested_cases
        self.predict_calls += 1
        return tuple(float(index) for index, _ in enumerate(candidates))


class _Evaluator:
    def __init__(self) -> None:
        self.module_calls = 0
        self.agent_calls = 0

    @property
    def identity_digest(self) -> str:
        return canonical_digest({"fake": "agentsquare-evaluator", "v": 1})

    def evaluate_module(self, *, module_type, module, episodes):
        self.module_calls += 1
        assert episodes == 50
        return AgentSquareModuleEvaluation(
            module_type=module_type,
            module_name=module["name"],
            performance=0.5,
            evidence_refs=(
                canonical_digest({
                    "kind": "module-eval",
                    "call": self.module_calls,
                }),
            ),
        )

    def evaluate_agent(self, *, agent, episodes):
        self.agent_calls += 1
        assert episodes == 50
        return AgentSquareEvaluation(
            agent=agent,
            performance=0.56 + self.agent_calls / 1000.0,
            evidence_refs=(
                canonical_digest({
                    "kind": "agent-eval",
                    "call": self.agent_calls,
                }),
            ),
        )


def _archives():
    return {
        "planning": (),
        "reasoning": (),
        "tooluse": (),
        "memory": (),
    }


def test_agentsquare_runs_full_ten_iteration_modular_search() -> None:
    program = AGENTSQUARE_ALFWORLD_OPTIMIZATION_PROGRAM
    assert program.kind is MachineKind.OPTIMIZATION
    assert program.program_id == "agentsquare.alfworld.later-official"

    model = _SearchModel()
    evaluator = _Evaluator()
    binding = AgentSquareOptimizationBinding(
        search_model=model,
        evaluator=evaluator,
    )
    initial = agentsquare_alfworld_initial_data(
        optimization_id="agentsquare:test:alfworld",
        module_archives=_archives(),
    )
    journal = InMemoryMachineJournal()
    execution = agentsquare_alfworld_host(journal).execute(
        machine_id="optimization:agentsquare:alfworld:test",
        instance_identity=agentsquare_alfworld_instance_identity(
            binding=binding,
            initial_data=initial,
        ),
        binding=binding,
        initial_data=initial,
    )

    assert execution.status is MachineStatus.COMPLETED
    assert execution.previous_value["iterations"] == 10
    assert model.evolve_calls == 10
    assert model.recombine_calls == 10
    assert model.predict_calls == 10
    assert evaluator.module_calls == 30
    assert evaluator.agent_calls == 40
    assert execution.data["iteration"] == 10
    assert len(execution.data["best_history"]) == 11
    assert execution.previous_value["best_performance"] > (
        AGENTSQUARE_FIDELITY.released_initial_performance
    )
