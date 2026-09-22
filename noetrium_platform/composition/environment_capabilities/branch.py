from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.environment.api import (
    ActionRequest,
    EnvironmentBranchStatePort,
    EnvironmentSession,
    Observation,
    require_action_result_identity,
)
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
    capability_request_digest,
)
from noetrium_platform.composition.environment_fork import (
    EnvironmentSessionOpener,
    fork_environment_session,
)
from noetrium_platform.composition.environment_replay import replay_environment_prefix
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    JsonInput,
    JsonValue,
    canonical_digest,
    freeze_json,
)

_REQUEST_SCHEMA = "noetrium.environment.branch-capability.request.v1"
_RESULT_SCHEMA = "noetrium.environment.branch-capability.result.v1"
_FORK = "fork_action"
_REPLAY = "replay_action"


def environment_branch_action_spec(
    action_type: str,
    payload: JsonInput,
) -> dict[str, JsonInput]:
    if not isinstance(action_type, str) or not action_type.strip():
        raise ValueError("environment branch action_type must be non-empty")
    return {"action_type": action_type, "payload": payload}


def environment_fork_action_payload(
    *,
    parent_branch_id: str,
    child_branch_id: str,
    source_cut_id: str,
    action_type: str,
    action_payload: JsonInput,
) -> dict[str, JsonInput]:
    for name, value in (
        ("parent_branch_id", parent_branch_id),
        ("child_branch_id", child_branch_id),
        ("source_cut_id", source_cut_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"environment fork payload {name} must be non-empty")
    return {
        "operation": _FORK,
        "parent_branch_id": parent_branch_id,
        "child_branch_id": child_branch_id,
        "source_cut_id": source_cut_id,
        "action": environment_branch_action_spec(action_type, action_payload),
    }


def environment_replay_action_payload(
    *,
    branch_id: str,
    source_cut_id: str,
    committed_actions: Sequence[Mapping[str, JsonInput]],
    action_type: str,
    action_payload: JsonInput,
    retain_branch: bool = False,
) -> dict[str, JsonInput]:
    for name, value in (("branch_id", branch_id), ("source_cut_id", source_cut_id)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"environment replay payload {name} must be non-empty")
    if not isinstance(committed_actions, Sequence) or isinstance(
        committed_actions, (str, bytes, bytearray)
    ):
        raise TypeError("environment replay committed_actions must be a sequence")
    actions = []
    for row in committed_actions:
        if not isinstance(row, Mapping):
            raise TypeError("environment replay committed action must be a mapping")
        action_kind = row.get("action_type")
        if not isinstance(action_kind, str) or not action_kind.strip():
            raise ValueError("environment replay committed action requires action_type")
        if "payload" not in row:
            raise ValueError("environment replay committed action requires payload")
        actions.append(environment_branch_action_spec(action_kind, row["payload"]))
    if type(retain_branch) is not bool:
        raise TypeError("environment replay retain_branch must be boolean")
    return {
        "operation": _REPLAY,
        "branch_id": branch_id,
        "source_cut_id": source_cut_id,
        "committed_actions": tuple(actions),
        "action": environment_branch_action_spec(action_type, action_payload),
        "retain_branch": retain_branch,
    }


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"environment branch {field} must be non-empty text")
    return value


def _action_spec(value: object, field: str) -> tuple[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"environment branch {field} must be a mapping")
    action_type = _text(value.get("action_type"), f"{field}.action_type")
    if "payload" not in value:
        raise ValueError(f"environment branch {field} requires payload")
    return action_type, freeze_json(value["payload"])


def _observation_payload(observation: Observation | None) -> JsonValue:
    if observation is None:
        return None
    if not isinstance(observation, Observation):
        raise TypeError("environment branch action observation must be Observation")
    return {
        "observation_id": observation.observation_id,
        "generation": observation.generation,
        "payload": observation.payload,
        "artifact_refs": observation.artifact_refs,
    }


def _effect_payload(effect: object) -> JsonValue:
    if effect is None:
        return None
    return freeze_json(
        {
            "effect_id": getattr(effect, "effect_id"),
            "request_digest": getattr(effect, "request_digest"),
            "effect_class": getattr(getattr(effect, "effect_class"), "value"),
            "certainty": getattr(getattr(effect, "certainty"), "value"),
            "provider_instance_id": getattr(effect, "provider_instance_id"),
            "verification_required": getattr(effect, "verification_required"),
            "before_artifact": getattr(effect, "before_artifact"),
            "after_artifact": getattr(effect, "after_artifact"),
            "provider_receipt": getattr(effect, "provider_receipt"),
        }
    )


class EnvironmentBranchCapabilityBinding:
    """Execute isolated scientific branch actions through the common capability ABI.

    Exact fork mode requires portable EnvironmentBranchState on both parent and
    child and proves state-digest equality before the child action is executed.

    Replay mode opens a fresh source-bound session and replays only the explicit
    committed action prefix. Its receipt proves ordered accepted replay, not hidden
    provider-state equality. The two proof strengths remain deliberately distinct.
    """

    def __init__(
        self,
        root: EnvironmentSession,
        *,
        root_session_id: str,
        root_branch_id: str,
        open_child: EnvironmentSessionOpener,
        capability_id: str = "environment.branch-state",
    ) -> None:
        if not isinstance(root, EnvironmentSession):
            raise TypeError("environment branch binding requires EnvironmentSession root")
        for name, value in (
            ("root_session_id", root_session_id),
            ("root_branch_id", root_branch_id),
            ("capability_id", capability_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"environment branch binding {name} must be non-empty")
        if not callable(open_child):
            raise TypeError("environment branch binding requires child-session opener")
        self._root = root
        self._root_session_id = root_session_id
        self._open_child = open_child
        self._branches: dict[str, tuple[str, EnvironmentSession]] = {
            root_branch_id: (root_session_id, root)
        }
        self._owned_children: set[str] = set()
        self._cache: dict[str, CapabilityResult] = {}
        self._descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            interface_version="1",
            request_schema=_REQUEST_SCHEMA,
            result_schema=_RESULT_SCHEMA,
            effect_class=EffectClass.IDEMPOTENT,
            deterministic=False,
        )

    @property
    def capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        return (self._descriptor,)

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        if capability_id != self._descriptor.capability_id:
            raise KeyError(capability_id)
        return self._descriptor

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        if request.capability_id != self._descriptor.capability_id:
            raise KeyError(request.capability_id)
        if not isinstance(request.payload, Mapping):
            raise TypeError("environment branch capability payload must be a mapping")
        request_digest = capability_request_digest(request)
        cached = self._cache.get(request_digest)
        if cached is not None:
            return cached

        operation = _text(request.payload.get("operation"), "operation")
        if operation == _FORK:
            result = self._fork_action(request, request_digest)
        elif operation == _REPLAY:
            result = self._replay_action(request, request_digest)
        else:
            raise ValueError(f"unsupported environment branch operation: {operation!r}")
        self._cache[request_digest] = result
        return result

    def close(self) -> None:
        for branch_id in tuple(self._owned_children):
            row = self._branches.pop(branch_id, None)
            if row is not None:
                row[1].close()
        self._owned_children.clear()
        self._cache.clear()

    def _action_request(
        self,
        request: CapabilityRequest,
        *,
        slot: str,
        action: object,
    ) -> ActionRequest:
        action_type, payload = _action_spec(action, slot)
        request_digest = capability_request_digest(request)
        return ActionRequest(
            action_id=f"environment-branch-action:{request_digest[:20]}:{slot}",
            action_type=action_type,
            payload=payload,
            context=request.context,
        )

    def _fork_action(
        self,
        request: CapabilityRequest,
        request_digest: str,
    ) -> CapabilityResult:
        payload = request.payload
        assert isinstance(payload, Mapping)
        parent_branch_id = _text(payload.get("parent_branch_id"), "parent_branch_id")
        child_branch_id = _text(payload.get("child_branch_id"), "child_branch_id")
        source_cut_id = _text(payload.get("source_cut_id"), "source_cut_id")
        if child_branch_id in self._branches:
            raise ValueError(f"environment child branch already exists: {child_branch_id}")
        try:
            parent_session_id, parent = self._branches[parent_branch_id]
        except KeyError as exc:
            raise KeyError(f"unknown environment parent branch: {parent_branch_id}") from exc
        if not isinstance(parent, EnvironmentBranchStatePort):
            raise TypeError("exact environment fork requires EnvironmentBranchStatePort parent")

        child_session_id = f"environment-branch:{request_digest[:24]}"
        child, receipt = fork_environment_session(
            parent,
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
            branch_id=child_branch_id,
            source_cut_id=source_cut_id,
            context=request.context,
            open_child=self._open_child,
        )
        self._branches[child_branch_id] = (child_session_id, child)
        self._owned_children.add(child_branch_id)
        try:
            action_request = self._action_request(
                request,
                slot="candidate",
                action=payload.get("action"),
            )
            action_result = require_action_result_identity(
                action_request,
                child.act(action_request),
                source="environment branch candidate action",
            )
            if not action_result.accepted:
                raise RuntimeError("environment branch candidate action was rejected")
            state = child.capture_branch_state(request.context)
        except BaseException:
            self._branches.pop(child_branch_id, None)
            self._owned_children.discard(child_branch_id)
            child.close()
            raise

        observation = action_result.observation
        result_payload = {
            "operation": _FORK,
            "parent_branch_id": parent_branch_id,
            "branch_id": child_branch_id,
            "source_cut_id": state.digest,
            "source_state_digest": receipt.source_state_digest,
            "restored_state_digest": receipt.restored_state_digest,
            "branch_state_digest": state.digest,
            "accepted": action_result.accepted,
            "action_type": action_request.action_type,
            "action_payload": action_request.payload,
            "observation": _observation_payload(observation),
            "effect": _effect_payload(action_result.effect),
            "proof": "portable_branch_state_digest_equality",
        }
        return CapabilityResult(
            capability_id=self._descriptor.capability_id,
            payload=result_payload,
            generation=None if observation is None else observation.generation,
            artifacts=() if observation is None else observation.artifact_refs,
            diagnostics={
                "operation": _FORK,
                "proof": "portable_branch_state_digest_equality",
                "fork_receipt_digest": canonical_digest(receipt),
            },
            request_digest=request_digest,
        )

    def _replay_action(
        self,
        request: CapabilityRequest,
        request_digest: str,
    ) -> CapabilityResult:
        payload = request.payload
        assert isinstance(payload, Mapping)
        branch_id = _text(payload.get("branch_id"), "branch_id")
        source_cut_id = _text(payload.get("source_cut_id"), "source_cut_id")
        task_id = request.context.task_id
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("environment replay branch requires task-bound context")
        raw_prefix = payload.get("committed_actions", ())
        if not isinstance(raw_prefix, Sequence) or isinstance(
            raw_prefix, (str, bytes, bytearray)
        ):
            raise TypeError("environment replay committed_actions must be a sequence")

        requests = tuple(
            self._action_request(request, slot=f"prefix:{index}", action=row)
            for index, row in enumerate(raw_prefix)
        )
        session_id = f"environment-replay:{request_digest[:24]}"
        child, replay = replay_environment_prefix(
            session_id=session_id,
            branch_id=branch_id,
            source_cut_id=source_cut_id,
            task_id=task_id,
            requests=requests,
            open_fresh=self._open_child,
        )
        retain = payload.get("retain_branch", False)
        if type(retain) is not bool:
            child.close()
            raise TypeError("environment replay retain_branch must be boolean")
        try:
            action_request = self._action_request(
                request,
                slot="candidate",
                action=payload.get("action"),
            )
            action_result = require_action_result_identity(
                action_request,
                child.act(action_request),
                source="environment replay candidate action",
            )
            if not action_result.accepted:
                raise RuntimeError("environment replay candidate action was rejected")
            observation = action_result.observation
            scientific_cut = canonical_digest(
                {
                    "replay_prefix_digest": replay.prefix_digest,
                    "candidate_action_id": action_result.action_id,
                    "candidate_observation_id": (
                        None if observation is None else observation.observation_id
                    ),
                }
            )
            if retain:
                if branch_id in self._branches:
                    raise ValueError(f"environment replay branch already exists: {branch_id}")
                self._branches[branch_id] = (session_id, child)
                self._owned_children.add(branch_id)
        except BaseException:
            child.close()
            raise
        if not retain:
            child.close()

        return CapabilityResult(
            capability_id=self._descriptor.capability_id,
            payload={
                "operation": _REPLAY,
                "branch_id": branch_id,
                "source_cut_id": scientific_cut,
                "prefix_digest": replay.prefix_digest,
                "accepted_prefix_action_ids": replay.accepted_action_ids,
                "accepted": action_result.accepted,
                "action_type": action_request.action_type,
                "action_payload": action_request.payload,
                "observation": _observation_payload(observation),
                "effect": _effect_payload(action_result.effect),
                "proof": "fresh_open_plus_ordered_prefix_replay",
            },
            generation=None if observation is None else observation.generation,
            artifacts=() if observation is None else observation.artifact_refs,
            diagnostics={
                "operation": _REPLAY,
                "proof": "fresh_open_plus_ordered_prefix_replay",
                "prefix_digest": replay.prefix_digest,
            },
            request_digest=request_digest,
        )


__all__ = [
    "EnvironmentBranchCapabilityBinding",
    "environment_branch_action_spec",
    "environment_fork_action_payload",
    "environment_replay_action_payload",
]
