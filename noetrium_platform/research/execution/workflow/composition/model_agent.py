from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from hashlib import sha256
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.api import ModelRequestRecorderPort, ModelRequestTokenBudget, ModelRequestTokenizationPort
from noetrium_platform.capabilities.api import (
    ModelEndpointDispatchPoolPort,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointRequestRejected,
)
from noetrium_platform.research.execution.policy.api import (
    ExecutionBudgetAuthorityPort,
    ExecutionBudgetDelta,
    ExecutionBudgetExceeded,
    ExecutionBudgetReservation,
    ExecutionBudgetReservationRequest,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ImmutableModelIdentity,
    JsonInput,
    JsonObject,
    canonical_bytes,
    canonical_digest,
    canonical_text,
    freeze_json,
    thaw_json,
    require_sha256,
)

from ..api import MethodAgentLoopPort, MethodAgentRequest, MethodAgentResult, MethodEvent


_MODEL_SAMPLING_SEED_MODULUS = 1 << 63
_MODEL_SAMPLING_SEED_MAX = _MODEL_SAMPLING_SEED_MODULUS - 1


def _model_sampling_seed(seed: int) -> int:
    if type(seed) is not int or seed < 0:
        raise ValueError("model sampling source seed must be a non-negative integer")
    return seed % _MODEL_SAMPLING_SEED_MODULUS


@dataclass(frozen=True, slots=True)
class CompiledMethodAgentRequest:
    body: JsonObject
    compiled_prompt_text: str
    prompt_generation_id: str
    prompt_id: str
    prompt_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.body, Mapping):
            raise TypeError("compiled Method model body must be a mapping")
        object.__setattr__(self, "body", freeze_json(self.body))
        for name in (
            "compiled_prompt_text",
            "prompt_generation_id",
            "prompt_id",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(
                    f"compiled Method model {name} must be non-empty"
                )
        require_sha256(
            self.prompt_digest,
            "compiled Method model prompt_digest",
        )


@runtime_checkable
class MethodAgentRequestFactoryPort(Protocol):
    @property
    def digest(self) -> str: ...

    def compile(
        self,
        request: MethodAgentRequest,
    ) -> CompiledMethodAgentRequest: ...


@dataclass(frozen=True, slots=True)
class MethodViewChatRequestFactory:
    """Compile one downstream-owned Method prompt exactly once per model call."""

    served_model_name: str
    generation_options: JsonObject
    _digest: str = field(
        init=False,
        repr=False,
        compare=False,
        metadata={"transient": True},
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.served_model_name, str)
            or not self.served_model_name.strip()
        ):
            raise ValueError("served model name is required")
        if not isinstance(self.generation_options, Mapping):
            raise TypeError("generation_options must be a mapping")
        object.__setattr__(
            self,
            "generation_options",
            freeze_json(self.generation_options),
        )
        forbidden = {"model", "messages"} & set(self.generation_options)
        if forbidden:
            raise ValueError(
                "generation_options must not override model/messages: "
                + ", ".join(sorted(forbidden))
            )
        object.__setattr__(
            self,
            "_digest",
            canonical_digest({
                "factory": "method-view-chat.v4",
                "served_model_name": self.served_model_name,
                "generation_options": self.generation_options,
                "sampling_seed_domain": {
                    "kind": "nonnegative-signed-int64",
                    "minimum": 0,
                    "maximum": _MODEL_SAMPLING_SEED_MAX,
                },
                "compile_contract": "single-projection",
            }),
        )

    @property
    def digest(self) -> str:
        return self._digest

    @staticmethod
    def _messages(
        request: MethodAgentRequest,
    ) -> tuple[dict[str, str], ...]:
        view = request.view
        prompt = view.get("prompt")
        if isinstance(prompt, str) and prompt.strip():
            return ({"role": "user", "content": prompt},)
        system = view.get("system")
        if system is not None and (
            not isinstance(system, str) or not system.strip()
        ):
            raise ValueError(
                "MethodProgram agent view system must be non-empty text"
            )
        payload = {
            str(key): value
            for key, value in view.items()
            if key not in {
                "system",
                "prompt",
                "prompt_generation_id",
                "prompt_id",
                "prompt_digest",
                "prompt_bundle",
                "model_generation",
            }
        }
        if not payload:
            raise ValueError(
                "MethodProgram agent view must provide model-visible prompt content"
            )
        user = canonical_text(payload)
        if isinstance(system, str):
            return (
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            )
        return ({"role": "user", "content": user},)

    def compile(
        self,
        request: MethodAgentRequest,
    ) -> CompiledMethodAgentRequest:
        if not isinstance(request, MethodAgentRequest):
            raise TypeError(
                "Method request factory requires MethodAgentRequest"
            )
        messages = self._messages(request)
        compiled_prompt_bytes = canonical_bytes(messages)
        compiled_prompt_text = compiled_prompt_bytes.decode("utf-8")

        view = request.view
        generation = view.get(
            "prompt_generation_id",
            view.get("prompt_bundle"),
        )
        prompt_id = view.get("prompt_id", view.get("prompt_bundle"))
        prompt_digest = view.get("prompt_digest")
        if generation is None:
            generation = f"method-view:{request.agent_id}"
        if prompt_id is None:
            prompt_id = generation
        if not isinstance(generation, str) or not generation.strip():
            raise ValueError(
                "method view prompt_generation_id must be non-empty text"
            )
        if not isinstance(prompt_id, str) or not prompt_id.strip():
            raise ValueError(
                "method view prompt_id must be non-empty text"
            )
        if prompt_digest is None:
            # The compiled prompt text is exactly the UTF-8 decoding of these
            # canonical bytes. Hash those bytes directly instead of wrapping
            # the entire prompt in another JSON object and re-encoding it.
            prompt_digest = sha256(compiled_prompt_bytes).hexdigest()
        else:
            require_sha256(
                prompt_digest,
                "method view prompt_digest",
            )

        options = dict(self.generation_options)
        dynamic = view.get("model_generation")
        if dynamic is not None:
            if not isinstance(dynamic, Mapping):
                raise TypeError(
                    "method view model_generation must be a mapping"
                )
            forbidden = {"model", "messages"} & set(dynamic)
            if forbidden:
                raise ValueError(
                    "method view model_generation must not override "
                    "model/messages: "
                    + ", ".join(sorted(forbidden))
                )
            options.update(dynamic)
        if request.context.assignment_seed is not None:
            ordinal = request.context.budget_usage.get("model_calls", 0)
            if type(ordinal) is not int or ordinal < 0:
                raise ValueError(
                    "model budget usage model_calls must be non-negative"
                )
            configured_seed = options.get("seed")
            namespace = (
                f"model:{request.agent_id}:call:{ordinal}:"
                f"configured:{configured_seed!r}"
            )
            options["seed"] = _model_sampling_seed(
                request.context.random_seed(namespace)
            )

        return CompiledMethodAgentRequest(
            body={
                "model": self.served_model_name,
                "messages": messages,
                **options,
            },
            compiled_prompt_text=compiled_prompt_text,
            prompt_generation_id=generation,
            prompt_id=prompt_id,
            prompt_digest=prompt_digest,
        )


@dataclass(frozen=True, slots=True)
class MethodModelEndpointBinding:
    """Actual immutable model binding for one Method agent identity."""

    agent_id: str
    role: str
    model: ImmutableModelIdentity
    request_factory_digest: str
    member_index: int = 0
    _digest: str = field(
        init=False,
        repr=False,
        compare=False,
        metadata={"transient": True},
    )

    def __post_init__(self) -> None:
        for name in ("agent_id", "role", "request_factory_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"method model binding {name} is required")
        if not isinstance(self.model, ImmutableModelIdentity):
            raise TypeError("method model binding model must be ImmutableModelIdentity")
        if type(self.member_index) is not int or self.member_index < 0:
            raise ValueError("method model binding member_index must be non-negative")
        require_sha256(
            self.request_factory_digest,
            "method model binding request_factory_digest",
        )
        object.__setattr__(
            self,
            "_digest",
            canonical_digest({
                "agent_id": self.agent_id,
                "role": self.role,
                "member_index": self.member_index,
                "model": self.model,
                "request_factory_digest": self.request_factory_digest,
            }),
        )

    @property
    def digest(self) -> str:
        return self._digest


@dataclass(frozen=True, slots=True)
class _MethodModelInvocationPlan:
    request: MethodAgentRequest
    compiled: CompiledMethodAgentRequest
    body: JsonObject
    token_budget: ModelRequestTokenBudget
    scope_id: str
    budget_request: ExecutionBudgetReservationRequest
    request_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.request, MethodAgentRequest):
            raise TypeError("Method model invocation plan requires request")
        if not isinstance(self.compiled, CompiledMethodAgentRequest):
            raise TypeError("Method model invocation plan requires compiled request")
        object.__setattr__(self, "body", freeze_json(self.body))
        if not isinstance(self.token_budget, ModelRequestTokenBudget):
            raise TypeError("Method model invocation plan requires token budget")
        if type(self.scope_id) is not str or not self.scope_id.strip():
            raise ValueError("Method model invocation plan requires budget scope")
        if not isinstance(
            self.budget_request,
            ExecutionBudgetReservationRequest,
        ):
            raise TypeError("Method model invocation plan requires budget request")
        if type(self.request_id) is not str or not self.request_id.strip():
            raise ValueError("Method model invocation plan requires request_id")


@dataclass(frozen=True, slots=True)
class MethodAgentPanelInvocation:
    member_index: int
    invoke: Callable[[], MethodAgentResult]
    abort: Callable[[], object]

    def __post_init__(self) -> None:
        if type(self.member_index) is not int or self.member_index < 0:
            raise ValueError("Method panel invocation member_index is invalid")
        if not callable(self.invoke) or not callable(self.abort):
            raise TypeError("Method panel invocation callbacks must be callable")


def _require_model_budget(
    request: MethodAgentRequest,
    body: Mapping[str, JsonInput],
) -> None:
    budget = request.context.trial_budget
    usage = request.context.budget_usage
    messages = body.get("messages")
    if not isinstance(messages, (tuple, list)):
        raise TypeError("model request messages must be a sequence")
    current_messages = len(messages)
    for field, increment in (
        ("max_turns", 1),
        ("max_model_calls", 1),
        ("max_messages", current_messages),
    ):
        limit = budget.get(field)
        if limit is None:
            continue
        if type(limit) is not int or limit < 1:
            raise ValueError(f"TrialBudget {field} must be positive integer")
        usage_field = {
            "max_turns": "turns",
            "max_model_calls": "model_calls",
            "max_messages": "messages",
        }[field]
        used = usage.get(usage_field, 0)
        if type(used) is not int or used < 0:
            raise ValueError(
                f"budget usage {usage_field} must be non-negative integer"
            )
        if used + increment > limit:
            raise RuntimeError(
                f"TrialBudget {field} exhausted: used={used} "
                f"next={increment} limit={limit}"
            )


class MethodModelAgentLoop:
    """Paper-agnostic MethodAgentLoop backed by a shared replica dispatch pool.

    The logical request is recorded exactly once before dispatch. The pool then
    selects one frozen physical deployment. No failed request is replayed onto a
    second replica, preserving the same fail-closed external-effect semantics as
    the endpoint pool itself.
    """

    def __init__(
        self,
        *,
        binding: MethodModelEndpointBinding,
        pool: ModelEndpointDispatchPoolPort,
        recorder: ModelRequestRecorderPort,
        request_factory: MethodAgentRequestFactoryPort,
        tokenization: ModelRequestTokenizationPort,
        execution_budget: ExecutionBudgetAuthorityPort,
    ) -> None:
        if not isinstance(binding, MethodModelEndpointBinding):
            raise TypeError("binding must be MethodModelEndpointBinding")
        if not isinstance(pool, ModelEndpointDispatchPoolPort):
            raise TypeError("pool must satisfy ModelEndpointDispatchPoolPort")
        if not isinstance(recorder, ModelRequestRecorderPort):
            raise TypeError("recorder must satisfy ModelRequestRecorderPort")
        if not isinstance(request_factory, MethodAgentRequestFactoryPort):
            raise TypeError("request_factory must satisfy MethodAgentRequestFactoryPort")
        if binding.request_factory_digest != request_factory.digest:
            raise ValueError("method model request factory identity drift")
        if not isinstance(tokenization, ModelRequestTokenizationPort):
            raise TypeError(
                "method model loop requires exact ModelRequestTokenizationPort"
            )
        if tokenization.identity.model != binding.model:
            raise ValueError("method model tokenization model identity drift")
        if not isinstance(execution_budget, ExecutionBudgetAuthorityPort):
            raise TypeError(
                "method model loop requires ExecutionBudgetAuthorityPort"
            )
        snapshot = pool.snapshot()
        require_sha256(snapshot.replica_set_digest, "method model replica_set_digest")
        self.binding = binding
        self.pool = pool
        self.recorder = recorder
        self.request_factory = request_factory
        self.tokenization = tokenization
        self.execution_budget = execution_budget
        self._replica_set_digest = snapshot.replica_set_digest
        self._selection_policy_digest = snapshot.selection_policy_digest
        require_sha256(
            self._selection_policy_digest,
            "method model selection_policy_digest",
        )
        self._identity_digest = canonical_digest({
            "binding_digest": self.binding.digest,
            "replica_set_digest": self._replica_set_digest,
            "selection_policy_digest": self._selection_policy_digest,
            "request_factory_digest": self.request_factory.digest,
            "tokenization_digest": self.tokenization.identity.digest(),
            "execution_budget_digest": self.execution_budget.identity_digest,
        })

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    @staticmethod
    def _response_cost_usd(usage: object) -> float | None:
        if not isinstance(usage, Mapping):
            return None
        value = usage.get("cost_usd")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            resolved = float(value)
            if resolved < 0.0:
                raise ValueError("model response cost_usd cannot be negative")
            return resolved
        return None

    def _plan_budgeted_body(
        self,
        request: MethodAgentRequest,
        body: Mapping[str, JsonInput],
        *,
        additional_reserved_tokens: int = 0,
    ) -> tuple[
        JsonObject,
        ModelRequestTokenBudget,
        str,
        ExecutionBudgetReservationRequest,
    ]:
        if (
            type(additional_reserved_tokens) is not int
            or additional_reserved_tokens < 0
        ):
            raise ValueError(
                "additional_reserved_tokens must be a non-negative integer"
            )
        if not request.context.trial_budget:
            raise RuntimeError(
                "canonical model execution requires a frozen TrialBudget"
            )
        scope_id = request.context.lifetime_id
        if type(scope_id) is not str or not scope_id.strip():
            raise RuntimeError(
                "scientific model execution requires assignment lifetime budget scope"
            )
        snapshot = self.execution_budget.require_active(scope_id)
        mutable = dict(body)
        messages = mutable.get("messages")
        if not isinstance(messages, (tuple, list)):
            raise TypeError("model request messages must be a sequence")
        token_budget = self.tokenization.inspect(
            mutable,
            context_length=self.binding.model.context_length,
        )
        max_tokens = request.context.trial_budget.get("max_tokens")
        if max_tokens is not None:
            if type(max_tokens) is not int or max_tokens <= 0:
                raise ValueError("TrialBudget max_tokens must be positive integer")
            used = (
                snapshot.usage.tokens
                + snapshot.reserved.tokens
                + additional_reserved_tokens
            )
            remaining = max_tokens - used
            if token_budget.input_tokens > remaining:
                raise ExecutionBudgetExceeded(
                    "TrialBudget max_tokens cannot admit model input: "
                    f"input={token_budget.input_tokens} remaining={remaining}"
                )
            output_cap = min(
                token_budget.requested_output_tokens,
                remaining - token_budget.input_tokens,
            )
            if "max_completion_tokens" in mutable:
                mutable["max_completion_tokens"] = output_cap
            else:
                mutable["max_tokens"] = output_cap
            token_budget = ModelRequestTokenBudget(
                tokenization_digest=token_budget.tokenization_digest,
                input_tokens=token_budget.input_tokens,
                requested_output_tokens=output_cap,
                context_length=token_budget.context_length,
            )
        requested = ExecutionBudgetDelta(
            turns=1,
            messages=len(messages),
            model_calls=1,
            tokens=token_budget.total_tokens,
        )
        charge_id = (
            "model:"
            + canonical_digest(
                {
                    "operation_id": request.context.operation_id,
                    "binding_digest": self.binding.digest,
                    "member_index": self.binding.member_index,
                }
            )
        )
        return (
            freeze_json(mutable),
            token_budget,
            scope_id,
            ExecutionBudgetReservationRequest(charge_id, requested),
        )

    def _plan_invocation(
        self,
        request: MethodAgentRequest,
        *,
        additional_reserved_tokens: int = 0,
    ) -> _MethodModelInvocationPlan:
        if not isinstance(request, MethodAgentRequest):
            raise TypeError("method model agent requires MethodAgentRequest")
        if request.agent_id != self.binding.agent_id:
            raise ValueError("method model agent target identity drift")
        operation_id = request.context.operation_id
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("method model invocation requires operation_id")
        compiled = self.request_factory.compile(request)
        body = compiled.body
        _require_model_budget(request, body)
        body, token_budget, scope_id, budget_request = (
            self._plan_budgeted_body(
                request,
                body,
                additional_reserved_tokens=additional_reserved_tokens,
            )
        )
        body_sha256 = canonical_digest(body)
        request_id = (
            "method-model-pool:"
            + canonical_digest(
                {
                    "schema": "method-model-pool-request.v2",
                    "operation_id": operation_id,
                    "binding_digest": self.binding.digest,
                    "replica_set_digest": self._replica_set_digest,
                    "body_sha256": body_sha256,
                }
            )
        )
        return _MethodModelInvocationPlan(
            request=request,
            compiled=compiled,
            body=body,
            token_budget=token_budget,
            scope_id=scope_id,
            budget_request=budget_request,
            request_id=request_id,
        )

    def _execute_reserved(
        self,
        plan: _MethodModelInvocationPlan,
        budget_reservation: ExecutionBudgetReservation,
    ) -> MethodAgentResult:
        if not isinstance(plan, _MethodModelInvocationPlan):
            raise TypeError("Method model dispatch requires invocation plan")
        if not isinstance(
            budget_reservation,
            ExecutionBudgetReservation,
        ):
            raise TypeError("Method model dispatch requires budget reservation")
        if budget_reservation.scope_id != plan.scope_id:
            raise ValueError("Method model budget reservation scope drift")
        if (
            budget_reservation.charge_id
            != plan.budget_request.charge_id
            or budget_reservation.requested
            != plan.budget_request.requested
        ):
            raise ValueError("Method model budget reservation identity drift")
        request = plan.request
        compiled = plan.compiled
        body = plan.body
        token_budget = plan.token_budget
        request_id = plan.request_id
        try:
            envelope = self.recorder.record(
                request_id=request_id,
                context=request.context,
                role=self.binding.role,
                model=self.binding.model,
                prompt_generation_id=compiled.prompt_generation_id,
                prompt_id=compiled.prompt_id,
                prompt_digest=compiled.prompt_digest,
                request_body=body,
                # MethodViewChatRequestFactory defines compiled prompt text as
                # canonical_text(body["messages"]). The durable request body is
                # therefore the sole lossless carrier; recorder reconstruction
                # regenerates the exact text without a second blob publication.
                compiled_prompt_text=None,
            )
            self.recorder.verify_visible_request(envelope, body)
        except BaseException as exc:
            try:
                self.execution_budget.abort(budget_reservation)
            except BaseException as budget_exc:
                raise ExceptionGroup(
                    "model request preparation and budget abort failed",
                    [exc, budget_exc],
                ) from exc
            raise

        remaining_seconds = self.execution_budget.remaining_seconds(plan.scope_id)
        if remaining_seconds is not None and remaining_seconds <= 0:
            try:
                self.execution_budget.abort(budget_reservation)
            except BaseException as budget_exc:
                raise ExceptionGroup(
                    "model dispatch budget expiry and reservation abort failed",
                    [
                        ExecutionBudgetExceeded(
                            "TrialBudget exhausted before model dispatch"
                        ),
                        budget_exc,
                    ],
                ) from budget_exc
            raise ExecutionBudgetExceeded(
                "TrialBudget exhausted before model dispatch"
            )

        try:
            dispatch = self.pool.complete(
                envelope,
                body,
                timeout_s=remaining_seconds,
            )
        except ModelEndpointRequestRejected as exc:
            try:
                self.execution_budget.abort(budget_reservation)
            except BaseException as budget_exc:
                raise ExceptionGroup(
                    "model request rejection and budget abort failed",
                    [exc, budget_exc],
                ) from exc
            raise
        except BaseException as exc:
            try:
                self.execution_budget.commit(
                    budget_reservation,
                    budget_reservation.requested,
                )
            except BaseException as budget_exc:
                raise ExceptionGroup(
                    "model invocation failure and conservative budget commit failed",
                    [exc, budget_exc],
                ) from exc
            raise
        if dispatch.replica_set_digest != self._replica_set_digest:
            raise RuntimeError("method model replica-set identity drift during dispatch")
        if dispatch.selection_policy_digest != self._selection_policy_digest:
            raise RuntimeError("method model selection-policy identity drift during dispatch")
        response = dispatch.response
        dispatch_request_digest = dispatch.request.digest()
        receipt = EffectReceipt(
            effect_id=f"model-response:{response.response_digest}",
            request_digest=dispatch_request_digest,
            effect_class=EffectClass.RECONCILABLE,
            certainty=EffectCertainty.EFFECT_CONFIRMED,
            provider_instance_id=response.deployment_id,
            verification_required=False,
            provider_receipt=response.response_digest,
        )

        usage_violations = []
        if (
            type(response.input_tokens) is int
            and not isinstance(response.input_tokens, bool)
            and type(response.output_tokens) is int
            and not isinstance(response.output_tokens, bool)
        ):
            actual_tokens = response.input_tokens + response.output_tokens
            if response.input_tokens != token_budget.input_tokens:
                usage_violations.append(
                    "tokenization_input_drift:"
                    f"planned={token_budget.input_tokens}:"
                    f"actual={response.input_tokens}"
                )
        else:
            actual_tokens = budget_reservation.requested.tokens
            if request.context.trial_budget.get("max_tokens") is not None:
                usage_violations.append("provider_token_usage_unverified")

        cost_usd = self._response_cost_usd(response.usage)
        if (
            request.context.trial_budget.get("max_cost_usd") is not None
            and cost_usd is None
        ):
            usage_violations.append("provider_cost_usage_unverified")

        budget_snapshot, budget_violations = self.execution_budget.commit(
            budget_reservation,
            ExecutionBudgetDelta(
                turns=1,
                messages=len(body["messages"]),
                model_calls=1,
                tokens=actual_tokens,
                cost_usd=0.0 if cost_usd is None else cost_usd,
            ),
        )
        usage_violations.extend(budget_violations)
        event = MethodEvent(
            "model.invocation",
            {
                "request_id": envelope.request_id,
                "request_digest": dispatch_request_digest,
                "response_digest": response.response_digest,
                "deployment_id": response.deployment_id,
                "deployment_generation": dispatch.request.deployment_generation,
                "replica_set_digest": dispatch.replica_set_digest,
                "selection_policy_digest": dispatch.selection_policy_digest,
                "selection_sequence": dispatch.selection_sequence,
                "model_id": self.binding.model.model_id,
                "model_revision": self.binding.model.revision,
                "engine": self.binding.model.engine,
                "engine_version": self.binding.model.engine_version,
                "prompt_generation_id": envelope.prompt_generation_id,
                "prompt_id": envelope.prompt_id,
                "prompt_digest": envelope.prompt_digest,
                "message_count": len(body["messages"]),
                "sampling_seed": body.get("seed"),
                "finish_reason": response.finish_reason,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost_usd": cost_usd,
                "usage": response.usage,
                "tokenization_digest": token_budget.tokenization_digest,
                "budget_scope_id": budget_reservation.scope_id,
                "budget_reservation_digest": (
                    budget_reservation.reservation_digest
                ),
                "budget_admission_digest": budget_snapshot.admission_digest,
            },
        )
        events = [event]
        if usage_violations:
            events.append(
                MethodEvent(
                    "budget.violation",
                    {
                        "scope_id": budget_reservation.scope_id,
                        "reservation_digest": (
                            budget_reservation.reservation_digest
                        ),
                        "violations": tuple(usage_violations),
                        "effect_id": receipt.effect_id,
                    },
                )
            )
        return MethodAgentResult(
            value=response.text,
            events=tuple(events),
            effect_receipts=(receipt,),
        )

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        plan = self._plan_invocation(request)
        reservation = self.execution_budget.reserve_batch(
            plan.scope_id,
            (plan.budget_request,),
        )[0]
        return self._execute_reserved(plan, reservation)


@runtime_checkable
class MethodAgentPanelExecutionPort(Protocol):
    """Physical fan-out mechanics for one scientific Method model panel."""

    def execute(
        self,
        role: str,
        invocations: tuple[MethodAgentPanelInvocation, ...],
        request: MethodAgentRequest,
    ) -> tuple[tuple[int, MethodAgentResult], ...]: ...


class MethodAgentPanelLoop:
    # Scientific panel cardinality is preserved; physical replicas stay inside
    # each member's ModelEndpoint pool.
    def __init__(
        self,
        role: str,
        members: tuple[tuple[int, MethodModelAgentLoop], ...],
        *,
        execution: MethodAgentPanelExecutionPort,
    ) -> None:
        if type(role) is not str or not role.strip():
            raise ValueError("method model panel role must be non-empty text")
        if type(members) is not tuple or not members:
            raise TypeError("method model panel requires a non-empty member tuple")
        indexes = tuple(row[0] for row in members)
        if indexes != tuple(range(len(members))):
            raise ValueError(
                "method model panel member indexes must be contiguous and ordered"
            )
        for member_index, loop in members:
            if not isinstance(loop, MethodModelAgentLoop):
                raise TypeError(
                    "method model panel members must be MethodModelAgentLoop"
                )
            if loop.binding.role != role:
                raise ValueError("method model panel member role drift")
            if loop.binding.member_index != member_index:
                raise ValueError("method model panel member index drift")
        if not isinstance(execution, MethodAgentPanelExecutionPort):
            raise TypeError(
                "method model panel execution must satisfy "
                "MethodAgentPanelExecutionPort"
            )
        self.role = role
        self.members = members
        self.execution = execution
        self._identity_digest = canonical_digest(
            {
                "router": "method-model-panel.v1",
                "role": role,
                "members": tuple(
                    (member_index, loop.identity_digest)
                    for member_index, loop in members
                ),
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if not isinstance(request, MethodAgentRequest):
            raise TypeError("method model panel requires MethodAgentRequest")
        if request.agent_id != self.role:
            raise ValueError("method model panel target identity drift")
        outputs = []
        events = []
        effects = []

        authority = self.members[0][1].execution_budget
        scope_id = request.context.lifetime_id
        if type(scope_id) is not str or not scope_id.strip():
            raise RuntimeError("Method model panel requires budget lifetime scope")
        plans = []
        additional_reserved_tokens = 0
        for member_index, loop in self.members:
            if loop.execution_budget is not authority:
                raise RuntimeError(
                    "Method model panel members must share one budget authority"
                )
            member_request = replace(
                request,
                agent_id=loop.binding.agent_id,
            )
            plan = loop._plan_invocation(
                member_request,
                additional_reserved_tokens=additional_reserved_tokens,
            )
            if plan.scope_id != scope_id:
                raise RuntimeError("Method model panel budget scope drift")
            plans.append((member_index, loop, plan))
            additional_reserved_tokens += plan.budget_request.requested.tokens

        reservations = authority.reserve_batch(
            scope_id,
            tuple(plan.budget_request for _, _, plan in plans),
        )
        if len(reservations) != len(plans):
            raise RuntimeError("Method model panel budget reservation cardinality drift")

        invocations = []
        for (member_index, loop, plan), reservation in zip(
            plans,
            reservations,
            strict=True,
        ):
            def invoke(
                loop=loop,
                plan=plan,
                reservation=reservation,
            ):
                return loop._execute_reserved(plan, reservation)

            def abort(
                authority=authority,
                reservation=reservation,
            ):
                return authority.abort(reservation)

            invocations.append(
                MethodAgentPanelInvocation(
                    member_index=member_index,
                    invoke=invoke,
                    abort=abort,
                )
            )

        rows = self.execution.execute(
            self.role,
            tuple(invocations),
            request,
        )
        expected_indexes = tuple(range(len(self.members)))
        indexes = tuple(row[0] for row in rows)
        if indexes != expected_indexes:
            raise RuntimeError(
                "method model panel execution returned non-canonical member order"
            )
        for member_index, result in rows:
            loop = self.members[member_index][1]
            if not isinstance(result, MethodAgentResult):
                raise TypeError(
                    "method model panel member must return MethodAgentResult"
                )
            outputs.append(
                {
                    "member_index": member_index,
                    "model_id": loop.binding.model.model_id,
                    "model_revision": loop.binding.model.revision,
                    "binding_digest": loop.binding.digest,
                    "value": thaw_json(result.value),
                }
            )
            events.extend(result.events)
            effects.extend(result.effect_receipts)
        events.append(
            MethodEvent(
                "model.panel.invocation",
                {
                    "role": self.role,
                    "member_count": len(self.members),
                    "member_binding_digests": tuple(
                        loop.binding.digest for _, loop in self.members
                    ),
                },
            )
        )
        return MethodAgentResult(
            value={"role": self.role, "members": tuple(outputs)},
            events=tuple(events),
            effect_receipts=tuple(effects),
        )


class MethodAgentLoopRouter:
    """Fail-closed router from Method agent identities to bound agent loops."""

    def __init__(self, bindings: Mapping[str, MethodAgentLoopPort]) -> None:
        if not isinstance(bindings, Mapping) or not bindings:
            raise ValueError("method agent router requires at least one binding")
        rows: dict[str, MethodAgentLoopPort] = {}
        identities: list[tuple[str, str]] = []
        for agent_id, loop in bindings.items():
            if not isinstance(agent_id, str) or not agent_id.strip():
                raise ValueError("method agent router ids must be non-empty text")
            if not isinstance(loop, MethodAgentLoopPort):
                raise TypeError("method agent router values must satisfy MethodAgentLoopPort")
            digest = getattr(loop, "identity_digest", None)
            require_sha256(digest, f"method agent router binding {agent_id} identity_digest")
            rows[agent_id] = loop
            identities.append((agent_id, digest))
        self._bindings = rows
        self._identity_digest = canonical_digest({
            "router": "method-agent-loop-router.v1",
            "bindings": tuple(sorted(identities)),
        })

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    @property
    def agent_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._bindings))

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if not isinstance(request, MethodAgentRequest):
            raise TypeError("method agent router requires MethodAgentRequest")
        try:
            loop = self._bindings[request.agent_id]
        except KeyError as exc:
            raise KeyError(
                f"no method agent binding for {request.agent_id!r}; "
                f"available={self.agent_ids!r}"
            ) from exc
        result = loop.run(request)
        if not isinstance(result, MethodAgentResult):
            raise TypeError("method agent binding must return MethodAgentResult")
        return result


__all__ = [
    "CompiledMethodAgentRequest",
    "MethodModelAgentLoop",
    "MethodAgentPanelExecutionPort",
    "MethodAgentPanelInvocation",
    "MethodAgentPanelLoop",
    "MethodAgentLoopRouter",
    "MethodAgentRequestFactoryPort",
    "MethodModelEndpointBinding",
    "MethodViewChatRequestFactory",
]
