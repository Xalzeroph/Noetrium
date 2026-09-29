from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.api import (
    ModelCapabilityInvocation,
    ModelCapabilityRequirement,
    ModelCapabilityResponse,
    ProjectModelBinding,
    ProjectModelBindingSet,
    ProjectModelRequest,
    ProjectModelResponse,
)
from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.evidence.artifact.content.providers import (
    DirectoryArtifactBlobStore,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    ImmutableModelIdentity,
    InMemoryMachineJournal,
    canonical_bytes,
    canonical_digest,
)
from noetrium_platform.research.execution.machines import (
    FunctionalModelInvocationRequestFactory,
    ModelInvocationCandidate,
    ModelInvocationProgram,
    ModelInvocationRuntime,
    ModelResponseSelectorRegistry,
)


def _requirement() -> ModelCapabilityRequirement:
    return ModelCapabilityRequirement(
        role="policy",
        prompt_generation_id="prompt-generation",
        prompt_id="policy-prompt",
        prompt_digest="8" * 64,
        required_capabilities=("generation",),
    )


def _binding(name: str, digit: str) -> ProjectModelBinding:
    return ProjectModelBinding(
        requirement_digest=_requirement().digest(),
        provider_id=f"provider-{name}",
        provider_profile_digest="2" * 64,
        role="policy",
        model=ImmutableModelIdentity(
            logical_name=name,
            model_id=f"repo/{name}",
            revision=f"revision-{name}",
            engine="vllm",
            engine_version="1",
            dtype="bfloat16",
            quantization=None,
            context_length=8192,
            tokenizer_revision="tok-1",
        ),
        deployment_id=f"deployment-{name}",
        deployment_generation=digit * 64,
        model_stack_digest="4" * 64,
        qualification_certificate_digest="5" * 64,
        runtime_qualification_digest="6" * 64,
        host_identity_digest="7" * 64,
        prompt_generation_id="prompt-generation",
        prompt_id="policy-prompt",
        prompt_digest="8" * 64,
        capabilities=("generation",),
        runtime_canary_evidence_digests=("9" * 64,),
        request_tokenization_digest="a" * 64,
    )


def _request_factory(
    root: Path,
    *,
    run_id: str,
) -> FunctionalModelInvocationRequestFactory:
    bodies = DirectoryArtifactBlobStore(root / "request-bodies")

    def build(binding: ProjectModelBinding, attempt_index: int) -> ProjectModelRequest:
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": "solve the same semantic task",
                }
            ],
            "attempt_index": attempt_index,
            "model": binding.model.model_id,
        }
        body_ref = bodies.put(
            canonical_bytes(body),
            media_type="application/json",
        )
        envelope = ModelRequestEnvelope(
            schema_version="model-request.v1",
            request_id=f"request:{binding.deployment_id}:{attempt_index}",
            context=ExecutionContext(
                run_id,
                "trace",
                f"span:{attempt_index}",
                decision_cycle_id="dc:model",
            ),
            role=binding.role,
            model=binding.model,
            prompt_generation_id=binding.prompt_generation_id or "",
            prompt_id=binding.prompt_id or "",
            prompt_digest=binding.prompt_digest or "",
            request_body=body_ref,
        )
        return ProjectModelRequest(
            binding.requirement_digest,
            envelope,
            body,
        )

    return FunctionalModelInvocationRequestFactory(
        "test.request-factory",
        "f" * 64,
        build,
    )


@dataclass
class _Client:
    binding: ProjectModelBinding
    text: str
    fail: bool = False
    calls: int = 0

    @property
    def requirement(self) -> ModelCapabilityRequirement:
        return _requirement()

    def invoke(
        self,
        invocation: ModelCapabilityInvocation[ProjectModelRequest],
    ) -> ModelCapabilityResponse[ProjectModelResponse]:
        self.calls += 1
        assert invocation.requirement_digest == self.requirement.digest()
        request = invocation.payload
        assert request.envelope.model == self.binding.model
        assert request.envelope.role == self.binding.role
        assert request.requirement_digest == self.binding.requirement_digest
        if self.fail:
            raise RuntimeError("test provider failure")
        response = ProjectModelResponse(
            request_digest=request.request_digest,
            binding_digest=self.binding.digest(),
            response_digest=canonical_digest({
                "binding": self.binding.digest(),
                "request": request.request_digest,
                "text": self.text,
            }),
            text=self.text,
        )
        return ModelCapabilityResponse(
            request_digest=invocation.request_digest,
            binding_digest=self.binding.digest(),
            output_schema_id=self.requirement.output_schema_id,
            output=response,
        )


def _runtime(
    tmp_path: Path,
    program: ModelInvocationProgram,
    journal: InMemoryMachineJournal,
) -> ModelInvocationRuntime:
    return ModelInvocationRuntime(
        program,
        journal=journal,
        responses=DirectoryArtifactBlobStore(tmp_path / "responses"),
    )


def _machine_id(
    *,
    run_id: str,
    invocation_id: str,
    input_digest: str,
    program: ModelInvocationProgram,
    binding_set: ProjectModelBindingSet,
) -> str:
    digest = canonical_digest({
        "run_id": run_id,
        "invocation_id": invocation_id,
        "input_digest": input_digest,
        "program_digest": program.program_digest,
        "binding_set_digest": binding_set.binding_set_digest,
    })
    return f"runtime-model:{run_id}:{digest[:24]}"


def test_panel_fails_closed_on_first_provider_failure(
    tmp_path: Path,
) -> None:
    first = _binding("first", "3")
    second = _binding("second", "b")
    admitted = ProjectModelBindingSet((first, second))
    first_client = _Client(first, "unused", fail=True)
    second_client = _Client(second, "must-not-run")
    selectors = ModelResponseSelectorRegistry()
    selectors.register(
        "first",
        lambda request: request.responses[0],
        implementation_digest="e" * 64,
    )
    program = ModelInvocationProgram(
        "paper.model-panel-fail-closed",
        "1",
        (
            ModelInvocationCandidate(first.digest(), "panel-member"),
            ModelInvocationCandidate(second.digest(), "panel-member"),
        ),
        selector="first",
        minimum_successes=2,
        target_successes=2,
    )
    journal = InMemoryMachineJournal()
    run_id = "run:model-panel-fail-closed"
    invocation_id = "decision:model"
    input_digest = canonical_digest({"semantic_input": "same task"})

    with pytest.raises(RuntimeError, match="failed closed"):
        _runtime(tmp_path, program, journal).invoke(
            run_id=run_id,
            invocation_id=invocation_id,
            binding_set=admitted,
            clients=(first_client, second_client),
            input_digest=input_digest,
            request_factory=_request_factory(tmp_path, run_id=run_id),
            selectors=selectors,
        )

    assert first_client.calls == 1
    assert second_client.calls == 0
    machine_id = _machine_id(
        run_id=run_id,
        invocation_id=invocation_id,
        input_digest=input_digest,
        program=program,
        binding_set=admitted,
    )
    event_types = tuple(
        event["type"]
        for commit in journal.commits(machine_id)
        for event in commit.event_payloads
        if isinstance(event, Mapping) and "type" in event
    )
    assert "runtime_model_attempt_failed" in event_types
    assert "runtime_model_attempt_completed" not in event_types
    assert "runtime_model_invocation_selected" not in event_types


def test_panel_selector_is_programmable_runtime_semantics(
    tmp_path: Path,
) -> None:
    short = _binding("short", "3")
    long = _binding("long", "b")
    admitted = ProjectModelBindingSet((short, long))
    clients = (
        _Client(short, "short"),
        _Client(long, "a much longer answer"),
    )
    selectors = ModelResponseSelectorRegistry()
    selectors.register(
        "longest",
        lambda request: max(
            request.responses,
            key=lambda response: len(response.text),
        ),
        implementation_digest="e" * 64,
    )
    program = ModelInvocationProgram(
        "paper.model-panel",
        "1",
        (
            ModelInvocationCandidate(short.digest(), "panel-member"),
            ModelInvocationCandidate(long.digest(), "panel-member"),
        ),
        selector="longest",
        minimum_successes=2,
        target_successes=2,
    )
    journal = InMemoryMachineJournal()
    run_id = "run:model-panel"
    outcome = _runtime(tmp_path, program, journal).invoke(
        run_id=run_id,
        invocation_id="panel:1",
        binding_set=admitted,
        clients=clients,
        input_digest=canonical_digest({"question": "panel"}),
        request_factory=_request_factory(tmp_path, run_id=run_id),
        selectors=selectors,
    )

    assert len(outcome.responses) == 2
    assert outcome.selected.text == "a much longer answer"
    assert tuple(client.calls for client in clients) == (1, 1)


def test_partial_success_threshold_continues_when_success_is_still_possible(
    tmp_path: Path,
) -> None:
    failing = _binding("failing", "3")
    good = _binding("good", "b")
    admitted = ProjectModelBindingSet((failing, good))
    clients = (_Client(failing, "unused", fail=True), _Client(good, "recovered"))
    selectors = ModelResponseSelectorRegistry()
    selectors.register(
        "first",
        lambda request: request.responses[0],
        implementation_digest="e" * 64,
    )
    program = ModelInvocationProgram(
        "paper.partial-panel",
        "1",
        (
            ModelInvocationCandidate(failing.digest(), "panel-member"),
            ModelInvocationCandidate(good.digest(), "panel-member"),
        ),
        selector="first",
        minimum_successes=1,
        target_successes=2,
    )
    outcome = _runtime(tmp_path, program, InMemoryMachineJournal()).invoke(
        run_id="run:partial-success",
        invocation_id="partial:1",
        binding_set=admitted,
        clients=clients,
        input_digest=canonical_digest({"question": "partial"}),
        request_factory=_request_factory(tmp_path, run_id="run:partial-success"),
        selectors=selectors,
    )
    assert outcome.selected.text == "recovered"
    assert outcome.failed_binding_digests == (failing.digest(),)
    assert tuple(client.calls for client in clients) == (1, 1)


def test_completed_model_invocation_reopens_without_provider_reexecution(
    tmp_path: Path,
) -> None:
    binding = _binding("single", "3")
    admitted = ProjectModelBindingSet((binding,))
    client = _Client(binding, "stable answer")
    program = ModelInvocationProgram(
        "paper.single-model",
        "1",
        (ModelInvocationCandidate(binding.digest()),),
    )
    journal = InMemoryMachineJournal()
    run_id = "run:model-reopen"
    invocation_id = "model:stable"
    input_digest = canonical_digest({"input": "stable"})
    request_factory = _request_factory(tmp_path, run_id=run_id)

    first = _runtime(tmp_path, program, journal).invoke(
        run_id=run_id,
        invocation_id=invocation_id,
        binding_set=admitted,
        clients=(client,),
        input_digest=input_digest,
        request_factory=request_factory,
    )
    assert client.calls == 1

    second = _runtime(tmp_path, program, journal).invoke(
        run_id=run_id,
        invocation_id=invocation_id,
        binding_set=admitted,
        clients=(client,),
        input_digest=input_digest,
        request_factory=request_factory,
    )
    assert client.calls == 1
    assert second.outcome_digest == first.outcome_digest
    assert second.selected.text == "stable answer"


def test_ordered_failover_stops_after_first_success(tmp_path: Path) -> None:
    first = _binding("fallback-first", "3")
    second = _binding("fallback-second", "b")
    third = _binding("fallback-third", "c")
    admitted = ProjectModelBindingSet((first, second, third))
    clients = (
        _Client(first, "unused", fail=True),
        _Client(second, "recovered"),
        _Client(third, "must-not-run"),
    )
    program = ModelInvocationProgram(
        "paper.ordered-failover",
        "1",
        (
            ModelInvocationCandidate(first.digest(), "fallback"),
            ModelInvocationCandidate(second.digest(), "fallback"),
            ModelInvocationCandidate(third.digest(), "fallback"),
        ),
        minimum_successes=1,
        target_successes=1,
    )
    outcome = _runtime(tmp_path, program, InMemoryMachineJournal()).invoke(
        run_id="run:ordered-failover",
        invocation_id="fallback:1",
        binding_set=admitted,
        clients=clients,
        input_digest=canonical_digest({"question": "fallback"}),
        request_factory=_request_factory(tmp_path, run_id="run:ordered-failover"),
    )
    assert outcome.selected.text == "recovered"
    assert outcome.failed_binding_digests == (first.digest(),)
    assert tuple(client.calls for client in clients) == (1, 1, 0)
