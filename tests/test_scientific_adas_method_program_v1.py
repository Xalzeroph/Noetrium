from __future__ import annotations

from hashlib import sha256

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.foundation.kernel.kernel import EffectClass, ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from research.reproductions.adas_meta_agent_search import (
    ADAS_META_AGENT_SEARCH_FIDELITY,
)
from research.reproductions.adas_meta_agent_search.program import (
    ADAS_MGSM_METHOD_PROGRAM,
    adas_mgsm_initial_state,
)


def _initial_archive() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "thought": f"seed thought {index}",
            "name": name,
            "code": (
                "def forward(self, taskInfo):\n"
                f"    return 'seed-{index}'\n"
            ),
        }
        for index, name in enumerate(
            ADAS_META_AGENT_SEARCH_FIDELITY.initial_archive_names
        )
    )


class _MetaAgent:
    def __init__(self) -> None:
        self.phase_calls: dict[str, int] = {}

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        phase = request.view["phase"]
        self.phase_calls[phase] = self.phase_calls.get(phase, 0) + 1
        generation = request.view["generation"]

        if phase == "proposal":
            return MethodAgentResult(
                value={
                    "thought": f"proposal thought {generation}",
                    "name": f"candidate-{generation}",
                    "code": (
                        "def forward(self, taskInfo):\n"
                        f"    return 'proposal-{generation}'\n"
                    ),
                }
            )
        if phase in {"reflection_1", "reflection_2"}:
            return MethodAgentResult(
                value={
                    "reflection": f"{phase} critique",
                    "thought": f"refined thought {generation}",
                    "name": f"candidate-{generation}",
                    "code": (
                        "def forward(self, taskInfo):\n"
                        f"    return '{phase}-{generation}'\n"
                    ),
                }
            )
        if phase == "debug":
            debug_index = self.phase_calls[phase]
            return MethodAgentResult(
                value={
                    "thought": f"refined thought {generation}",
                    "debug_thought": "repair the low-accuracy implementation",
                    "name": f"candidate-{generation}",
                    "code": (
                        "def forward(self, taskInfo):\n"
                        f"    return 'debugged-{debug_index}-{generation}'\n"
                    ),
                }
            )
        raise AssertionError(f"unexpected ADAS meta phase: {phase}")


class _CandidateExecution:
    def __init__(self) -> None:
        self.requests: list[CapabilityRequest] = []
        self.generation_one_attempts = 0

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        assert capability_id == "workbench.candidate-program.execute"
        return CapabilityDescriptor(
            capability_id,
            "1",
            "candidate-program.request.v1",
            "candidate-program.result.v1",
            EffectClass.IDEMPOTENT,
        )

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        self.requests.append(request)
        payload = request.payload
        candidate_id = payload["candidate_id"]
        source_text = payload["source_text"]

        mean_accuracy = 0.75
        if candidate_id == "adas:mgsm:generation:1":
            self.generation_one_attempts += 1
            if self.generation_one_attempts == 1:
                mean_accuracy = 0.0

        measurements = (
            ("mean_accuracy", mean_accuracy),
            ("fitness_median", mean_accuracy),
            ("fitness_ci_lower", max(0.0, mean_accuracy - 0.05)),
            ("fitness_ci_upper", min(1.0, mean_accuracy + 0.05)),
        )
        rows = tuple(
            {
                "measurement_id": measurement_id,
                "record_digest": sha256(
                    f"{candidate_id}:{len(self.requests)}:{measurement_id}".encode()
                ).hexdigest(),
                "scalar": scalar,
            }
            for measurement_id, scalar in measurements
        )
        source_digest = sha256(source_text.encode()).hexdigest()
        receipt_digest = sha256(
            f"receipt:{candidate_id}:{len(self.requests)}:{source_digest}".encode()
        ).hexdigest()
        return CapabilityResult(
            request.capability_id,
            {
                "candidate_id": candidate_id,
                "candidate_digest": source_digest,
                "source_artifact_id": f"source:{source_digest[:16]}",
                "source_content_sha256": source_digest,
                "execution_request_digest": sha256(
                    f"request:{receipt_digest}".encode()
                ).hexdigest(),
                "execution_receipt_digest": receipt_digest,
                "status": "succeeded",
                "failure_code": None,
                "measurements": rows,
                "measurement_record_digests": tuple(
                    row["record_digest"] for row in rows
                ),
                "evidence_digests": (
                    sha256(f"evidence:{receipt_digest}".encode()).hexdigest(),
                ),
                "isolation_evidence_digests": (
                    sha256(f"isolation:{receipt_digest}".encode()).hexdigest(),
                ),
            },
        )


def test_adas_method_program_runs_archive_search_reflection_debug_and_execution() -> None:
    models = _MetaAgent()
    candidates = _CandidateExecution()
    result = UniversalMethodMachine(max_steps=4096).run(
        ADAS_MGSM_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            ExecutionContext("adas-run", "trace", "span", task_id="mgsm:cut"),
            capabilities=candidates,
            agent_loop=models,
        ),
        initial_state=adas_mgsm_initial_state(_initial_archive()),
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["generation_slots"] == 30
    assert result.value["successful_generations"] == 30
    assert result.value["failed_generations"] == 0
    assert result.value["archive_size"] == 37
    assert result.value["best_validation_accuracy"] == 0.75

    assert models.phase_calls["proposal"] == 30
    assert models.phase_calls["reflection_1"] == 30
    assert models.phase_calls["reflection_2"] == 30
    assert models.phase_calls["debug"] == 1

    # Seven initial archive evaluations + one low-fitness candidate + its debugged
    # replacement + the other 29 accepted generation candidates.
    assert len(candidates.requests) == 38
    assert candidates.generation_one_attempts == 2

    accepted = result.value["archive"][-1]
    assert accepted["generation"] == 30
    assert "debug_thought" not in accepted
    assert "reflection" not in accepted


def test_adas_method_program_binds_candidate_execution_as_platform_capability() -> None:
    fidelity = ADAS_META_AGENT_SEARCH_FIDELITY
    program = ADAS_MGSM_METHOD_PROGRAM
    assert program.required_capabilities == ("workbench.candidate-program.execute",)
    assert program.configuration["source_commit"] == fidelity.audited_commit
    assert program.configuration["benchmark"] == "mgsm"
    assert program.configuration["generation_budget"] == 30
    assert program.configuration["candidate_execution_attempt_budget"] == 3
    assert program.configuration["validation_size"] == 128
    assert program.configuration["test_size"] == 800
    assert program.configuration["bootstrap_samples"] == 100000
    assert program.configuration["bootstrap_confidence_level"] == 0.95


class _FailFirstGenerationExecution(_CandidateExecution):
    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        self.requests.append(request)
        payload = request.payload
        candidate_id = payload["candidate_id"]
        source_text = payload["source_text"]

        fail = candidate_id == "adas:mgsm:generation:1"
        mean_accuracy = 0.0 if fail else 0.8
        if fail:
            self.generation_one_attempts += 1

        measurements = (
            ("mean_accuracy", mean_accuracy),
            ("fitness_median", mean_accuracy),
            ("fitness_ci_lower", max(0.0, mean_accuracy - 0.05)),
            ("fitness_ci_upper", min(1.0, mean_accuracy + 0.05)),
        )
        rows = tuple(
            {
                "measurement_id": measurement_id,
                "record_digest": sha256(
                    f"{candidate_id}:{len(self.requests)}:{measurement_id}".encode()
                ).hexdigest(),
                "scalar": scalar,
            }
            for measurement_id, scalar in measurements
        )
        source_digest = sha256(source_text.encode()).hexdigest()
        receipt_digest = sha256(
            f"receipt:{candidate_id}:{len(self.requests)}:{source_digest}".encode()
        ).hexdigest()
        return CapabilityResult(
            request.capability_id,
            {
                "candidate_id": candidate_id,
                "candidate_digest": source_digest,
                "source_artifact_id": f"source:{source_digest[:16]}",
                "source_content_sha256": source_digest,
                "execution_request_digest": sha256(
                    f"request:{receipt_digest}".encode()
                ).hexdigest(),
                "execution_receipt_digest": receipt_digest,
                "status": "succeeded",
                "failure_code": None,
                "measurements": rows,
                "measurement_record_digests": tuple(
                    row["record_digest"] for row in rows
                ),
                "evidence_digests": (
                    sha256(f"evidence:{receipt_digest}".encode()).hexdigest(),
                ),
                "isolation_evidence_digests": (
                    sha256(f"isolation:{receipt_digest}".encode()).hexdigest(),
                ),
            },
        )


def test_adas_never_admits_unexecuted_final_debug_source_with_stale_fitness() -> None:
    models = _MetaAgent()
    candidates = _FailFirstGenerationExecution()
    result = UniversalMethodMachine(max_steps=4096).run(
        ADAS_MGSM_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            ExecutionContext(
                "adas-stale-fitness-run",
                "trace",
                "span",
                task_id="mgsm:cut",
            ),
            capabilities=candidates,
            agent_loop=models,
        ),
        initial_state=adas_mgsm_initial_state(_initial_archive()),
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["generation_slots"] == 30
    assert result.value["successful_generations"] == 29
    assert result.value["failed_generations"] == 1
    assert result.value["archive_size"] == 36
    assert candidates.generation_one_attempts == 3

    # The released source asks for one more debug rewrite after the third failed
    # evaluation. We preserve that model call, but the resulting source was never
    # executed and therefore cannot enter the scientific archive.
    assert models.phase_calls["debug"] == 3
    archive_names = tuple(row["name"] for row in result.value["archive"])
    assert "candidate-1" not in archive_names

    evaluated_generation_one_sources = {
        request.payload["source_text"]
        for request in candidates.requests
        if request.payload["candidate_id"] == "adas:mgsm:generation:1"
    }
    assert len(evaluated_generation_one_sources) == 3
    assert (
        "def forward(self, taskInfo):\n"
        "    return 'debugged-3-1'\n"
    ) not in evaluated_generation_one_sources
