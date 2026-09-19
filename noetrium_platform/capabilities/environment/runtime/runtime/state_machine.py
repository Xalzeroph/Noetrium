from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json

from noetrium_platform.capabilities.environment.api.provider import (
    EnvironmentProviderCapabilities,
    EnvironmentSessionDiagnostics,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    InMemoryMachineJournal,
    JsonObject,
    MachineJournalPort,
    MachineSnapshotStorePort,
    canonical_bytes,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.machines import (
    EnvironmentMachineSpec,
    MachineEvent,
    environment_initial_data,
    execution_context_payload,
    state_machine_environment_host,
)

from ..api import (
    ActionIdentityViolation,
    ActionRequest,
    ActionResult,
    EnvironmentCapability,
    EnvironmentCapabilityDescriptor,
    EnvironmentCapabilityUnsupported,
    EnvironmentBranchState,
    EnvironmentIdentity,
    EnvironmentImplementation,
    EnvironmentProviderCapabilities,
    EnvironmentQuery,
    EnvironmentQueryResult,
    EnvironmentSession,
    EnvironmentSessionDiagnostics,
    Observation,
    StateMachineDynamicsPort,
    StateMachineEnvironmentSpec,
    action_request_digest,
    freeze_json_mapping,
    thaw_json_mapping,
)
from .state_machine_checkpoint import (
    AppliedStateMachineAction,
    StateMachineCheckpointCodec,
    StateMachineCheckpointError,
)


@dataclass(frozen=True, slots=True)
class StateMachineEnvironmentImplementation(EnvironmentImplementation):
    spec: StateMachineEnvironmentSpec
    dynamics: StateMachineDynamicsPort

    def __post_init__(self) -> None:
        if self.dynamics.identity != self.spec.dynamics:
            raise ValueError("state-machine dynamics identity does not match the environment spec")

    @property
    def identity(self) -> EnvironmentIdentity:
        return EnvironmentIdentity(
            environment_id=self.spec.environment_id,
            implementation_version=self.spec.implementation_version,
            abi_version=self.spec.abi_version,
            schema_version=self.spec.schema_version,
            artifact_digest=self.spec.scientific_identity_digest(),
        )


def _observation_from_payload(value: object) -> Observation:
    if not isinstance(value, Mapping):
        raise TypeError("EnvironmentMachine observation payload must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError("EnvironmentMachine observation payload must decode to an object")
    refs = decoded.get("artifact_refs", ())
    if not isinstance(refs, (tuple, list)):
        raise TypeError("EnvironmentMachine observation artifact_refs must be a sequence")
    return Observation(
        observation_id=decoded["observation_id"],
        generation=decoded["generation"],
        payload=decoded["payload"],
        artifact_refs=tuple(refs),
    )


def _effect_from_payload(value: object) -> EffectReceipt:
    if not isinstance(value, Mapping):
        raise TypeError("EnvironmentMachine effect payload must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError("EnvironmentMachine effect payload must decode to an object")
    return EffectReceipt(
        effect_id=decoded["effect_id"],
        request_digest=decoded["request_digest"],
        effect_class=EffectClass(decoded["effect_class"]),
        certainty=EffectCertainty(decoded["certainty"]),
        provider_instance_id=decoded.get("provider_instance_id"),
        verification_required=decoded.get("verification_required", False),
        before_artifact=decoded.get("before_artifact"),
        after_artifact=decoded.get("after_artifact"),
        provider_receipt=decoded.get("provider_receipt"),
    )


def _effect_payload(effect: EffectReceipt) -> dict[str, object]:
    return {
        "effect_id": effect.effect_id,
        "request_digest": effect.request_digest,
        "effect_class": effect.effect_class.value,
        "certainty": effect.certainty.value,
        "provider_instance_id": effect.provider_instance_id,
        "verification_required": effect.verification_required,
        "before_artifact": effect.before_artifact,
        "after_artifact": effect.after_artifact,
        "provider_receipt": effect.provider_receipt,
    }


def _action_result_from_payload(value: object) -> ActionResult:
    if not isinstance(value, Mapping):
        raise TypeError("EnvironmentMachine action result must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError("EnvironmentMachine action result must decode to an object")
    observation_raw = decoded.get("observation")
    effect_raw = decoded.get("effect")
    diagnostics = decoded.get("diagnostics", {})
    if not isinstance(diagnostics, dict):
        raise TypeError("EnvironmentMachine action diagnostics must be an object")
    return ActionResult(
        action_id=decoded["action_id"],
        accepted=decoded["accepted"],
        observation=(
            None
            if observation_raw is None
            else _observation_from_payload(observation_raw)
        ),
        effect=None if effect_raw is None else _effect_from_payload(effect_raw),
        diagnostics=diagnostics,
    )


def _action_result_payload(result: ActionResult) -> dict[str, object]:
    observation = result.observation
    return {
        "action_id": result.action_id,
        "accepted": result.accepted,
        "observation": (
            None
            if observation is None
            else {
                "observation_id": observation.observation_id,
                "generation": observation.generation,
                "payload": observation.payload,
                "artifact_refs": observation.artifact_refs,
            }
        ),
        "effect": None if result.effect is None else _effect_payload(result.effect),
        "diagnostics": result.diagnostics,
    }


class StateMachineEnvironmentSession(EnvironmentSession):
    """Deterministic environment facade over one authoritative EnvironmentMachine."""

    _BRANCH_STATE_SCHEMA = "environment.state-machine.branch-state.v1"
    _CHECKPOINT_SCHEMA = StateMachineCheckpointCodec.SCHEMA

    def __init__(
        self,
        *,
        session_id: str,
        implementation: StateMachineEnvironmentImplementation,
        journal: MachineJournalPort,
        snapshot_store: MachineSnapshotStorePort | None = None,
    ) -> None:
        if type(session_id) is not str or not session_id.strip():
            raise ValueError("state-machine session_id must be non-empty")
        if not isinstance(journal, MachineJournalPort):
            raise TypeError("state-machine environment requires MachineJournalPort")
        self.session_id = session_id
        self.implementation = implementation
        self.identity = implementation.identity
        self._provider_instance_id = f"{self.identity.environment_id}:{session_id}"
        self._checkpoint_codec = StateMachineCheckpointCodec(
            session_id=session_id,
            environment_generation=self.generation,
            provider_instance_id=self._provider_instance_id,
        )

        machine_spec = EnvironmentMachineSpec(
            environment_id=self.identity.environment_id,
            session_id=session_id,
            generation=self.generation,
            provider_instance_id=self._provider_instance_id,
            action_types=implementation.spec.action_types,
            initial_state=implementation.spec.initial_state,
            state_schema_id=f"environment.state-machine.{implementation.spec.schema_version}",
        )
        host = state_machine_environment_host(
            implementation.dynamics,
            journal=journal,
            snapshot_store=snapshot_store,
        )
        self._machine = host.open_session(
            machine_id=(
                f"environment:{self.identity.environment_id}:{session_id}"
            ),
            instance_identity={
                "session_id": session_id,
                "environment_id": self.identity.environment_id,
                "environment_spec_digest": machine_spec.spec_digest,
            },
            binding=None,
        )
        if not self._machine.started:
            self._machine.start(
                environment_initial_data(machine_spec),
                command_id=f"{self._machine.machine_id}:start",
            )
        elif self._machine.data.get("environment_spec_digest") != machine_spec.spec_digest:
            raise ValueError("existing EnvironmentMachine spec identity mismatch")

    @property
    def generation(self) -> str:
        return self.identity.artifact_digest

    @property
    def machine_cut(self):
        head = self._machine.machine.journal.latest(self._machine.machine_id)
        if head is None:
            return None
        from noetrium_platform.foundation.kernel.kernel import MachineCut
        return MachineCut.from_commit(head)

    def _event(self, kind: str, payload: JsonObject, *, command_id: str) -> JsonObject:
        self._machine.step(
            {
                "event": MachineEvent(
                    kind,
                    payload,
                    source=self.session_id,
                ).as_payload()
            },
            command_id=command_id,
        )
        value = self._machine.previous_value
        if not isinstance(value, Mapping):
            raise ValueError("EnvironmentMachine event produced no object result")
        decoded = thaw_json(value)
        if not isinstance(decoded, dict):
            raise TypeError("EnvironmentMachine result must decode to an object")
        return decoded

    def observe(self, context: ExecutionContext) -> Observation:
        if not isinstance(context, ExecutionContext):
            raise TypeError("state-machine observe requires ExecutionContext")
        value = self._event(
            "environment.observe",
            {"context": execution_context_payload(context)},
            command_id=f"{self._machine.machine_id}:observe:{self._machine.revision}",
        )
        return _observation_from_payload(value["observation"])

    def query(self, request: EnvironmentQuery) -> EnvironmentQueryResult:
        if not isinstance(request, EnvironmentQuery):
            raise TypeError("state-machine query requires EnvironmentQuery")
        if request.query_type not in {"state", "capabilities"}:
            raise EnvironmentCapabilityUnsupported(f"query:{request.query_type}")
        value = self._event(
            "environment.query",
            {
                "query_id": request.query_id,
                "query_type": request.query_type,
                "payload": request.payload,
                "context": execution_context_payload(request.context),
            },
            command_id=(
                f"{self._machine.machine_id}:query:"
                f"{request.query_id}:{self._machine.revision}"
            ),
        )
        result_payload = value["payload"]
        if not isinstance(result_payload, Mapping):
            raise TypeError("EnvironmentMachine query result payload is invalid")
        if request.query_type == "capabilities":
            result_payload = {
                "capabilities": [
                    {
                        "capability_id": descriptor.capability_id,
                        "version": descriptor.version,
                        "action_types": list(descriptor.action_types),
                        "query_types": list(descriptor.query_types),
                        "metadata": descriptor.metadata,
                    }
                    for descriptor in self.capability_descriptors()
                ]
            }
        return EnvironmentQueryResult(
            request.query_id,
            True,
            dict(result_payload),
            _observation_from_payload(value["observation"]),
        )

    def capability_descriptors(self) -> tuple[EnvironmentCapabilityDescriptor, ...]:
        return (
            EnvironmentCapabilityDescriptor(
                "environment.state_machine",
                self.implementation.spec.schema_version,
                action_types=self.implementation.spec.action_types,
                query_types=("state", "capabilities"),
                metadata={"deterministic": True, "machine_backed": True},
            ),
        )

    def act(self, request: ActionRequest) -> ActionResult:
        if not isinstance(request, ActionRequest):
            raise TypeError("state-machine act requires ActionRequest")
        if not isinstance(request.payload, Mapping):
            raise TypeError("state-machine action payload must be an object")
        payload = freeze_json_mapping(request.payload, field="action_payload")
        normalized = ActionRequest(
            request.action_id,
            request.action_type,
            payload,
            request.context,
        )
        request_digest = action_request_digest(normalized)

        # Action identity is a domain-level idempotency contract. Resolve an
        # already-applied action from the authoritative EnvironmentMachine
        # ledger before issuing another revision-fenced MachineCommand.
        actions_value = self._machine.data.get("actions", {})
        if not isinstance(actions_value, Mapping):
            raise TypeError("EnvironmentMachine action ledger must be an object")
        prior = actions_value.get(request.action_id)
        if prior is not None:
            if not isinstance(prior, Mapping):
                raise TypeError("EnvironmentMachine action ledger row must be an object")
            if prior.get("request_digest") != request_digest:
                raise ActionIdentityViolation(
                    f"environment action identity was reused with drift: {request.action_id}"
                )
            prior_result = prior.get("result")
            if not isinstance(prior_result, Mapping):
                raise TypeError("EnvironmentMachine action ledger result must be an object")
            return _action_result_from_payload(prior_result)

        value = self._event(
            "environment.act",
            {
                "action_id": normalized.action_id,
                "action_type": normalized.action_type,
                "payload": normalized.payload,
                "context": execution_context_payload(normalized.context),
            },
            command_id=(
                f"{self._machine.machine_id}:action:"
                f"{normalized.action_id}:{request_digest[:16]}"
            ),
        )
        return _action_result_from_payload(value["action_result"])

    def reconcile(self, effect: EffectReceipt, context: ExecutionContext) -> EffectReceipt:
        if not isinstance(effect, EffectReceipt):
            raise TypeError("state-machine reconcile requires EffectReceipt")
        if not isinstance(context, ExecutionContext):
            raise TypeError("state-machine reconcile requires ExecutionContext")
        action_id = effect.provider_receipt
        if type(action_id) is not str or not action_id.strip():
            raise ActionIdentityViolation(
                "state-machine effect does not identify an applied session action"
            )
        value = self._event(
            "environment.reconcile",
            {
                "action_id": action_id,
                "request_digest": effect.request_digest,
                "context": execution_context_payload(context),
            },
            command_id=(
                f"{self._machine.machine_id}:reconcile:"
                f"{action_id}:{effect.request_digest[:16]}:{self._machine.revision}"
            ),
        )
        return _effect_from_payload(value["effect"])

    def capture_branch_state(self, context: ExecutionContext) -> EnvironmentBranchState:
        if not isinstance(context, ExecutionContext):
            raise TypeError("state-machine branch capture requires ExecutionContext")
        if context.task_id is None or not context.task_id.strip():
            raise ValueError("state-machine branch state requires task_id")
        value = self._event(
            "environment.branch.capture",
            {"context": execution_context_payload(context)},
            command_id=(
                f"{self._machine.machine_id}:branch-capture:"
                f"{context.task_id}:{self._machine.revision}"
            ),
        )
        state_value = value["state"]
        if not isinstance(state_value, Mapping):
            raise TypeError("EnvironmentMachine branch state must be an object")
        state_document = thaw_json_mapping(
            freeze_json_mapping(state_value, field="branch_state.state")
        )
        payload = canonical_bytes({
            "schema": self._BRANCH_STATE_SCHEMA,
            "state": state_document,
        })
        return EnvironmentBranchState.capture(
            environment=self.identity,
            source_session_id=self.session_id,
            task_id=context.task_id,
            generation=self.generation,
            state_schema_id=self._BRANCH_STATE_SCHEMA,
            state_digest=value["state_digest"],
            opaque_payload=payload,
        )

    def restore_branch_state(
        self,
        state: EnvironmentBranchState,
        context: ExecutionContext,
    ) -> None:
        if not isinstance(context, ExecutionContext):
            raise TypeError("state-machine branch restore requires ExecutionContext")
        if context.task_id is None or not context.task_id.strip():
            raise ValueError("state-machine branch restore requires task_id")
        state.verify_for(
            environment=self.identity,
            task_id=context.task_id,
            generation=self.generation,
        )
        try:
            document = json.loads(state.opaque_payload.decode("utf-8"))
            if (
                not isinstance(document, Mapping)
                or set(document) != {"schema", "state"}
                or document["schema"] != self._BRANCH_STATE_SCHEMA
                or not isinstance(document["state"], Mapping)
            ):
                raise ValueError("state-machine branch state schema mismatch")
            restored = freeze_json_mapping(
                document["state"],
                field="branch_state.state",
            )
            if canonical_digest(restored) != state.state_digest:
                raise ValueError("state-machine branch state digest mismatch")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("invalid state-machine branch state") from exc
        self._event(
            "environment.branch.restore",
            {
                "state": restored,
                "state_digest": state.state_digest,
                "context": execution_context_payload(context),
            },
            command_id=(
                f"{self._machine.machine_id}:branch-restore:"
                f"{state.digest[:16]}:{self._machine.revision}"
            ),
        )

    def checkpoint(self) -> bytes:
        data = self._machine.data
        state = data.get("state")
        sequence = data.get("observation_sequence")
        actions_value = data.get("actions", {})
        if not isinstance(state, Mapping):
            raise TypeError("EnvironmentMachine state must be an object")
        if type(sequence) is not int or sequence < 0:
            raise ValueError("EnvironmentMachine observation_sequence is invalid")
        if not isinstance(actions_value, Mapping):
            raise TypeError("EnvironmentMachine action ledger must be an object")
        actions: dict[str, AppliedStateMachineAction] = {}
        for action_id, row in actions_value.items():
            if type(action_id) is not str or not isinstance(row, Mapping):
                raise TypeError("EnvironmentMachine action ledger row is invalid")
            request_digest = row.get("request_digest")
            result_value = row.get("result")
            if type(request_digest) is not str:
                raise TypeError("EnvironmentMachine action request_digest is invalid")
            actions[action_id] = AppliedStateMachineAction(
                request_digest,
                _action_result_from_payload(result_value),
            )
        return self._checkpoint_codec.encode(
            state=state,
            observation_sequence=sequence,
            actions=actions,
        )

    def restore(self, payload: bytes) -> None:
        decoded = self._checkpoint_codec.decode(payload)
        actions = {
            action_id: {
                "request_digest": applied.request_digest,
                "result": _action_result_payload(applied.result),
            }
            for action_id, applied in decoded.actions
        }
        self._event(
            "environment.snapshot.restore",
            {
                "state": decoded.state,
                "state_digest": canonical_digest(decoded.state),
                "observation_sequence": decoded.observation_sequence,
                "actions": actions,
            },
            command_id=(
                f"{self._machine.machine_id}:snapshot-restore:"
                f"{canonical_digest(payload)[:16]}:{self._machine.revision}"
            ),
        )

    def diagnostics_snapshot(self) -> EnvironmentSessionDiagnostics:
        data = self._machine.data
        closed = data.get("closed") is True
        state_digest = data.get("state_digest")
        return EnvironmentSessionDiagnostics(
            session_id=self.session_id,
            environment=self.identity,
            generation=self.generation,
            ready=not closed,
            closed=closed,
            capabilities=EnvironmentProviderCapabilities((
                EnvironmentCapability.SNAPSHOT,
                EnvironmentCapability.RESTORE,
                EnvironmentCapability.BRANCH_STATE,
                EnvironmentCapability.RECONCILE,
                EnvironmentCapability.DIAGNOSTICS,
                EnvironmentCapability.QUERY,
            )),
            state_digest=state_digest if isinstance(state_digest, str) else None,
        )

    def diagnostics(self) -> dict[str, object]:
        data = self._machine.data
        snapshot = self.diagnostics_snapshot()
        actions = data.get("actions", {})
        return {
            "environment": "state_machine",
            "session_id": snapshot.session_id,
            "generation": snapshot.generation,
            "closed": snapshot.closed,
            "state_digest": snapshot.state_digest,
            "observation_sequence": data.get("observation_sequence", 0),
            "known_action_ids": len(actions) if isinstance(actions, Mapping) else 0,
            "machine_revision": self._machine.revision,
        }

    def close(self) -> None:
        if self._machine.data.get("closed") is True:
            return
        self._event(
            "environment.close",
            {},
            command_id=f"{self._machine.machine_id}:close",
        )


class StateMachineEnvironmentRuntime:
    """Lifecycle owner for injected closed-world dynamics and shared Machine authority."""

    def __init__(
        self,
        *,
        journal: MachineJournalPort | None = None,
        snapshot_store: MachineSnapshotStorePort | None = None,
    ) -> None:
        self._journal = journal if journal is not None else InMemoryMachineJournal()
        self._snapshot_store = snapshot_store

    def open_session(
        self,
        implementation: object,
        *,
        session_id: str,
        services: object,
    ) -> StateMachineEnvironmentSession:
        del services
        if not isinstance(implementation, StateMachineEnvironmentImplementation):
            raise TypeError(
                "StateMachineEnvironmentRuntime requires StateMachineEnvironmentImplementation"
            )
        return StateMachineEnvironmentSession(
            session_id=session_id,
            implementation=implementation,
            journal=self._journal,
            snapshot_store=self._snapshot_store,
        )


__all__ = [
    "StateMachineCheckpointError",
    "StateMachineEnvironmentImplementation",
    "StateMachineEnvironmentRuntime",
    "StateMachineEnvironmentSession",
]
