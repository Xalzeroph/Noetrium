from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.capabilities.model.api import (
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
    ModelInvocationMode,
    ModelInvocationProgram,
    ModelInvocationRuntime,
    ModelResponseSelectorRegistry,
)


def _binding(name: str, digit: str) -> ProjectModelBinding:
    return ProjectModelBinding(
        requirement_digest="1" * 64,
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

    def complete(self, request: ProjectModelRequest) -> ProjectModelResponse:
        self.calls += 1
        assert request.envelope.model == self.binding.model
        assert request.envelope.role == self.binding.role
        assert request.requirement_digest == self.binding.requirement_digest
        if self.fail:
            raise RuntimeError("test provider failure")
        return ProjectModelResponse(
            request_digest=request.request_digest,
            binding_digest=self.binding.digest(),
            response_digest=canonical_digest({
                "binding": self.binding.digest(),
                "request": request.request_digest,
                "text": self.text,
            }),
            text=self.text,
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


def test_fallback_attempts_are_separate_machine_transitions(
    tmp_path: Path,
) -> None:
    primary = _binding("primary", "3")
    fallback = _binding("fallback", "b")
    admitted = ProjectModelBindingSet((primary, fallback))
    primary_client = _Client(primary, "unused", fail=True)
    fallback_client = _Client(fallback, "fallback answer")
    program = ModelInvocationProgram(
        "paper.model-fallback",
        "1",
        ModelInvocationMode.FALLBACK,
        (
            ModelInvocationCandidate(primary.digest(), "primary"),
            ModelInvocationCandidate(fallback.digest(), "provider-failure"),
        ),
    )
    journal = InMemoryMachineJournal()
    run_id = "run:model-fallback"
    invocation_id = "decision:model"
    input_digest = canonical_digest({"semantic_input": "same task"})
    outcome = _runtime(tmp_path, program, journal).invoke(
        run_id=run_id,
        invocation_id=invocation_id,
        binding_set=admitted,
        clients=(primary_client, fallback_client),
        input_digest=input_digest,
        request_factory=_request_factory(tmp_path, run_id=run_id),
    )

    assert outcome.selected.text == "fallback answer"
    assert outcome.failed_binding_digests == (primary.digest(),)
    assert primary_client.calls == 1
    assert fallback_client.calls == 1
    assert outcome.selected.selection_receipt is not None
    assert outcome.selected.selection_receipt.attempt_index == 2
    assert (
        outcome.selected.selection_receipt.previous_selection_receipt_digest
        is not None
    )

    machine_id = _machine_id(
        run_id=run_id,
        invocation_id=invocation_id,
        input_digest=input_digest,
        program=program,
        binding_set=admitted,
    )
    commits = journal.commits(machine_id)
    assert len(commits) == 4
    event_types = tuple(
        event["type"]
        for commit in commits
        for event in commit.event_payloads
        if isinstance(event, dict) and "type" in event
    )
    assert "runtime_model_attempt_failed" in event_types
    assert "runtime_model_attempt_completed" in event_types
    assert "runtime_model_invocation_selected" in event_types


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
        ModelInvocationMode.PANEL,
        (
            ModelInvocationCandidate(short.digest(), "panel-member"),
            ModelInvocationCandidate(long.digest(), "panel-member"),
        ),
        selector="longest",
        minimum_successes=2,
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


def test_panel_can_select_after_final_member_failure_when_minimum_is_met(
    tmp_path: Path,
) -> None:
    good = _binding("good", "3")
    failing = _binding("failing", "b")
    admitted = ProjectModelBindingSet((good, failing))
    clients = (
        _Client(good, "usable"),
        _Client(failing, "unused", fail=True),
    )
    selectors = ModelResponseSelectorRegistry()
    selectors.register(
        "first",
        lambda request: request.responses[0],
        implementation_digest="d" * 64,
    )
    program = ModelInvocationProgram(
        "paper.partial-panel",
        "1",
        ModelInvocationMode.PANEL,
        (
            ModelInvocationCandidate(good.digest(), "panel-member"),
            ModelInvocationCandidate(failing.digest(), "panel-member"),
        ),
        selector="first",
        minimum_successes=1,
    )
    run_id = "run:partial-panel"
    outcome = _runtime(
        tmp_path,
        program,
        InMemoryMachineJournal(),
    ).invoke(
        run_id=run_id,
        invocation_id="panel:partial",
        binding_set=admitted,
        clients=clients,
        input_digest=canonical_digest({"question": "partial"}),
        request_factory=_request_factory(tmp_path, run_id=run_id),
        selectors=selectors,
    )
    assert outcome.selected.text == "usable"
    assert outcome.failed_binding_digests == (failing.digest(),)


def test_completed_model_invocation_reopens_without_provider_reexecution(
    tmp_path: Path,
) -> None:
    binding = _binding("single", "3")
    admitted = ProjectModelBindingSet((binding,))
    client = _Client(binding, "stable answer")
    program = ModelInvocationProgram(
        "paper.single-model",
        "1",
        ModelInvocationMode.SINGLE,
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
