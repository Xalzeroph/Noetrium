from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import uuid4

from noetrium_platform.capabilities.environment.api import (
    ActionReconciliationDisposition,
    ActionReconciliationResult,
    ActionRequest,
    ActionResult,
    Observation,
    action_request_digest,
)
from noetrium_platform.capabilities.environment.providers import (
    JsonlProcessMessage,
    JsonlProcessSpec,
    JsonlProcessTransport,
)
from noetrium_platform.capabilities.environment.text_world.api import (
    TextWorldActionKind,
    TextWorldEnvironmentSpec,
)
from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    JsonInput,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.foundation.kernel.kernel.durability import atomic_replace_bytes, durable_unlink
from noetrium_platform.infrastructure.lifecycle.host.providers import LocalOperatingSystemRoute
from noetrium_platform.substrate.api import ProcessSupervisorPort
from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle

from ..authority import ALFWORLD_TEXT_RUNTIME_AUTHORITY_DIGEST
from ..cut import ALFWORLD_PAPER_EVAL_REVISION, ALFWORLD_PAPER_EVAL_SPLIT

_STATE_SCHEMA = "alfworld.text-session-state.v1"
_HANDLE_SCHEMA = "alfworld.text-session-action.v1"
_CONTAINER_DATA_ROOT = "/data/alfworld"
_CONTAINER_CONFIG = "/opt/noetrium/alfworld/paper_eval_config.yaml"


class _WorkerTransport(Protocol):
    @property
    def started(self) -> bool: ...

    def start(self) -> None: ...

    def send(self, command: str, payload: Mapping[str, JsonInput], *, request_id: str) -> None: ...

    def read(self, *, timeout_s: float) -> JsonlProcessMessage: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class AlfworldTextRuntimeSpec:
    image: str
    runtime_artifact_digest: str
    data_root: str
    task_gamefile: str
    recovery_root: str
    session_id: str
    split: str = ALFWORLD_PAPER_EVAL_SPLIT
    command_timeout_s: float = 45.0
    docker_executable: str = "docker"

    def __post_init__(self) -> None:
        if any(
            type(value) is not str or not value.strip()
            for value in (
                self.image,
                self.data_root,
                self.task_gamefile,
                self.recovery_root,
                self.session_id,
                self.split,
                self.docker_executable,
            )
        ):
            raise ValueError("ALFWorld text runtime identity fields must be non-empty")
        require_sha256(self.runtime_artifact_digest, "ALFWorld runtime_artifact_digest")
        relative = self.task_gamefile.replace("\\", "/").strip("/")
        if not relative or relative.startswith("../") or "/../" in relative or relative.startswith("json_2.1.1/"):
            raise ValueError("ALFWorld task_gamefile must be relative to json_2.1.1/valid_unseen")
        if not relative.endswith("game.tw-pddl"):
            raise ValueError("ALFWorld task_gamefile must identify game.tw-pddl")
        if self.command_timeout_s <= 0:
            raise ValueError("ALFWorld command timeout must be positive")
        object.__setattr__(self, "task_gamefile", relative)

    @property
    def provider_instance_id(self) -> str:
        return canonical_digest(
            {
                "runtime_artifact_digest": self.runtime_artifact_digest,
                "task_gamefile": self.task_gamefile,
                "session_id": self.session_id,
            }
        )

    @property
    def text_world_spec(self) -> TextWorldEnvironmentSpec:
        return TextWorldEnvironmentSpec(
            environment_id="alfworld.text.paper-eval.v1",
            revision=ALFWORLD_PAPER_EVAL_REVISION,
            action_vocabulary=(TextWorldActionKind.COMMAND,),
            metadata={
                "split": self.split,
                "task_gamefile": self.task_gamefile,
                "runtime_artifact_digest": self.runtime_artifact_digest,
                "source_authority_digest": ALFWORLD_TEXT_RUNTIME_AUTHORITY_DIGEST,
            },
        )


class AlfworldTextSession:
    """Crash-durable ALFWorld text session backed by a replaceable JSONL worker.

    The durable journal is authoritative. A worker is always reconstructed as
    reset(task) + replay(committed actions), so process-local state can never
    outrank durable experiment truth.
    """

    action_recovery_durability = "crash_durable"

    def __init__(
        self,
        spec: AlfworldTextRuntimeSpec,
        *,
        transport_factory: Callable[[], _WorkerTransport],
    ) -> None:
        if not isinstance(spec, AlfworldTextRuntimeSpec):
            raise TypeError("ALFWorld session requires AlfworldTextRuntimeSpec")
        self.runtime = spec
        self.spec = spec.text_world_spec
        self._transport_factory = transport_factory
        self._transport: _WorkerTransport | None = None
        self._lock = RLock()
        self._request_counter = 0
        session_key = hashlib.sha256(spec.session_id.encode("utf-8")).hexdigest()
        self._root = Path(spec.recovery_root) / session_key
        self._prepared_root = self._root / "prepared"
        self._state_path = self._root / "state.json"
        self._root.mkdir(parents=True, exist_ok=True)
        self._prepared_root.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()
        self._recover_worker()

    @property
    def provider_instance_id(self) -> str:
        return self.runtime.provider_instance_id

    def _default_state(self, initial: Mapping[str, JsonInput]) -> dict[str, JsonInput]:
        return {
            "schema": _STATE_SCHEMA,
            "session_id": self.runtime.session_id,
            "task_gamefile": self.runtime.task_gamefile,
            "runtime_artifact_digest": self.runtime.runtime_artifact_digest,
            "initial": dict(initial),
            "records": [],
        }

    def _load_state(self) -> dict[str, JsonInput] | None:
        if not self._state_path.exists():
            return None
        raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema") != _STATE_SCHEMA:
            raise RuntimeError("ALFWorld durable state schema mismatch")
        if raw.get("session_id") != self.runtime.session_id:
            raise RuntimeError("ALFWorld durable state session mismatch")
        if raw.get("task_gamefile") != self.runtime.task_gamefile:
            raise RuntimeError("ALFWorld durable state task mismatch")
        if raw.get("runtime_artifact_digest") != self.runtime.runtime_artifact_digest:
            raise RuntimeError("ALFWorld durable state runtime artifact drift")
        if not isinstance(raw.get("initial"), dict) or not isinstance(raw.get("records"), list):
            raise RuntimeError("ALFWorld durable state is malformed")
        return raw

    def _persist_state(self, state: Mapping[str, JsonInput]) -> None:
        payload = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
        atomic_replace_bytes(self._state_path, payload)

    def _records(self) -> list[dict[str, JsonInput]]:
        if self._state is None:
            return []
        rows = self._state["records"]
        assert isinstance(rows, list)
        return [dict(row) for row in rows if isinstance(row, dict)]

    def _current_worker_payload(self) -> dict[str, JsonInput]:
        if self._state is None:
            raise RuntimeError("ALFWorld session is not initialized")
        rows = self._records()
        value = rows[-1]["worker"] if rows else self._state["initial"]
        if not isinstance(value, dict):
            raise RuntimeError("ALFWorld durable worker payload is malformed")
        return dict(value)

    def _generation_for_count(self, count: int) -> str:
        if self._state is None:
            raise RuntimeError("ALFWorld session is not initialized")
        rows = self._records()
        if count < 0 or count > len(rows):
            raise ValueError("ALFWorld generation count is out of range")
        canonical_rows = [
            {
                "action_id": row["action_id"],
                "request_digest": row["request_digest"],
                "payload": row["payload"],
                "worker": row["worker"],
            }
            for row in rows[:count]
        ]
        return canonical_digest(
            {
                "runtime_artifact_digest": self.runtime.runtime_artifact_digest,
                "task_gamefile": self.runtime.task_gamefile,
                "initial": self._state["initial"],
                "records": canonical_rows,
            }
        )

    def _generation(self) -> str:
        return self._generation_for_count(len(self._records()))

    def _next_request_id(self, command: str) -> str:
        self._request_counter += 1
        return f"alfworld:{self.runtime.session_id}:{command}:{self._request_counter}:{uuid4().hex[:8]}"

    def _roundtrip(self, command: str, payload: Mapping[str, JsonInput]) -> dict[str, JsonInput]:
        transport = self._transport
        if transport is None:
            raise RuntimeError("ALFWorld worker transport is not running")
        request_id = self._next_request_id(command)
        transport.send(command, payload, request_id=request_id)
        message = transport.read(timeout_s=self.runtime.command_timeout_s)
        value = dict(message.value)
        if value.get("request_id") != request_id:
            raise RuntimeError("ALFWorld worker request correlation mismatch")
        if message.kind == "error":
            raise RuntimeError(
                f"ALFWorld worker failed [{value.get('code', 'UNKNOWN')}]: {value.get('message', '')}"
            )
        if message.kind != command and not (command == "close" and message.kind == "closed"):
            raise RuntimeError(
                f"ALFWorld worker message mismatch: command={command} kind={message.kind}"
            )
        value.pop("type", None)
        value.pop("request_id", None)
        return value

    def _start_transport(self) -> None:
        transport = self._transport_factory()
        transport.start()
        self._transport = transport

    def _invalidate_worker(self) -> None:
        transport, self._transport = self._transport, None
        if transport is not None:
            try:
                transport.close()
            except BaseException:
                pass

    def _recover_worker(self) -> None:
        self._invalidate_worker()
        self._start_transport()
        try:
            initial = self._roundtrip("reset", {"gamefile": self.runtime.task_gamefile})
            if self._state is None:
                candidate = self._default_state(initial)
                self._persist_state(candidate)
                self._state = candidate
                return
            if initial != self._state["initial"]:
                raise RuntimeError("ALFWorld reset observation drifted from durable authority")
            for index, record in enumerate(self._records()):
                payload = record.get("payload")
                if not isinstance(payload, dict) or type(payload.get("text")) is not str:
                    raise RuntimeError("ALFWorld durable action payload is malformed")
                replayed = self._roundtrip("step", {"action": payload["text"]})
                if replayed != record.get("worker"):
                    raise RuntimeError(f"ALFWorld replay drift at committed action {index}")
        except BaseException:
            self._invalidate_worker()
            raise

    @staticmethod
    def _action_text(request: ActionRequest) -> str:
        if request.action_type != TextWorldActionKind.COMMAND.value:
            raise ValueError(f"unsupported ALFWorld action type: {request.action_type}")
        payload = request.payload
        if not isinstance(payload, Mapping) or type(payload.get("text")) is not str:
            raise TypeError("ALFWorld command payload requires text")
        text = str(payload["text"]).strip()
        if not text:
            raise ValueError("ALFWorld command text must be non-empty")
        return text

    def _observation_from_worker(
        self,
        worker: Mapping[str, JsonInput],
        *,
        ordinal: int,
        action_id: str | None,
    ) -> Observation:
        text = worker.get("observation")
        if type(text) is not str:
            raise RuntimeError("ALFWorld worker observation must be text")
        won = bool(worker.get("won", False))
        done = bool(worker.get("done", False))
        commands = worker.get("admissible_commands", [])
        if not isinstance(commands, list):
            commands = []
        return Observation(
            observation_id=(
                f"alfworld:{self.runtime.session_id}:initial"
                if action_id is None
                else f"alfworld:{self.runtime.session_id}:{ordinal}:{action_id}"
            ),
            generation=self._generation_for_count(ordinal),
            payload={
                "text": text,
                "done": done,
                "info": {
                    "won": won,
                    "gamefile": str(worker.get("gamefile", self.runtime.task_gamefile)),
                },
                "admissible_commands": [str(item) for item in commands],
            },
            artifact_refs=(),
        )

    def observe(self, context: ExecutionContext) -> Observation:
        del context
        with self._lock:
            rows = self._records()
            action_id = None if not rows else str(rows[-1]["action_id"])
            return self._observation_from_worker(
                self._current_worker_payload(),
                ordinal=len(rows),
                action_id=action_id,
            )

    def prepare_action_recovery(
        self, request: ActionRequest, context: ExecutionContext
    ) -> PreparedEffectHandle:
        with self._lock:
            if request.context != context:
                raise ValueError("ALFWorld prepared action context mismatch")
            self._action_text(request)
            document: dict[str, JsonInput] = {
                "schema": _HANDLE_SCHEMA,
                "session_id": self.runtime.session_id,
                "task_gamefile": self.runtime.task_gamefile,
                "runtime_artifact_digest": self.runtime.runtime_artifact_digest,
                "action_id": request.action_id,
                "request_digest": action_request_digest(request),
                "expected_generation": self._generation(),
                "payload": dict(request.payload),
            }
            opaque = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
            key = hashlib.sha256(request.action_id.encode("utf-8")).hexdigest()
            atomic_replace_bytes(self._prepared_root / f"{key}.json", opaque)
            return PreparedEffectHandle.build(
                request_id=request.action_id,
                request_digest=action_request_digest(request),
                provider_schema=_HANDLE_SCHEMA,
                opaque_payload=opaque,
                provider_instance_id=self.provider_instance_id,
            )

    def _decode_handle(self, handle: PreparedEffectHandle) -> dict[str, JsonInput]:
        if not isinstance(handle, PreparedEffectHandle) or handle.provider_schema != _HANDLE_SCHEMA:
            raise ValueError("ALFWorld prepared handle schema mismatch")
        if handle.provider_instance_id != self.provider_instance_id:
            raise ValueError("ALFWorld prepared handle provider mismatch")
        raw = json.loads(handle.opaque_payload.decode("utf-8"))
        if not isinstance(raw, dict) or raw.get("schema") != _HANDLE_SCHEMA:
            raise ValueError("ALFWorld prepared handle payload is invalid")
        if raw.get("session_id") != self.runtime.session_id or raw.get("task_gamefile") != self.runtime.task_gamefile:
            raise ValueError("ALFWorld prepared handle session/task mismatch")
        if raw.get("runtime_artifact_digest") != self.runtime.runtime_artifact_digest:
            raise ValueError("ALFWorld prepared handle runtime drift")
        return raw

    def _find_record(self, action_id: str) -> tuple[int, dict[str, JsonInput]] | None:
        for index, row in enumerate(self._records()):
            if row.get("action_id") == action_id:
                return index, row
        return None

    def _result_from_record(self, index: int, record: Mapping[str, JsonInput]) -> ActionResult:
        worker = record.get("worker")
        if not isinstance(worker, Mapping):
            raise RuntimeError("ALFWorld committed worker result is malformed")
        before = self._generation_for_count(index)
        after = self._generation_for_count(index + 1)
        action_id = str(record["action_id"])
        digest = str(record["request_digest"])
        return ActionResult(
            action_id=action_id,
            accepted=True,
            observation=self._observation_from_worker(worker, ordinal=index + 1, action_id=action_id),
            effect=EffectReceipt(
                effect_id=f"alfworld-action:{action_id}",
                request_digest=digest,
                effect_class=EffectClass.RECONCILABLE,
                certainty=EffectCertainty.EFFECT_CONFIRMED,
                provider_instance_id=self.provider_instance_id,
                verification_required=False,
                before_artifact=before,
                after_artifact=after,
                provider_receipt=action_id,
            ),
            diagnostics={
                "environment": "alfworld",
                "task_gamefile": self.runtime.task_gamefile,
                "ordinal": index + 1,
                "done": bool(worker.get("done", False)),
                "won": bool(worker.get("won", False)),
            },
        )

    def execute_prepared_action(
        self, request: ActionRequest, handle: PreparedEffectHandle
    ) -> ActionResult:
        with self._lock:
            document = self._decode_handle(handle)
            digest = action_request_digest(request)
            if handle.request_id != request.action_id or handle.request_digest != digest:
                raise ValueError("ALFWorld prepared handle request identity mismatch")
            if document.get("request_digest") != digest or document.get("action_id") != request.action_id:
                raise ValueError("ALFWorld prepared payload request identity mismatch")
            existing = self._find_record(request.action_id)
            if existing is not None:
                return self._result_from_record(*existing)
            if document.get("expected_generation") != self._generation():
                raise RuntimeError("ALFWorld prepared action generation is stale")
            text = self._action_text(request)
            if self._transport is None:
                self._recover_worker()
            before_count = len(self._records())
            try:
                worker = self._roundtrip("step", {"action": text})
                record: dict[str, JsonInput] = {
                    "action_id": request.action_id,
                    "request_digest": digest,
                    "payload": dict(request.payload),
                    "worker": worker,
                }
                assert self._state is not None
                next_state = dict(self._state)
                next_state["records"] = [*self._records(), record]
                self._persist_state(next_state)
                self._state = next_state
            except BaseException:
                self._invalidate_worker()
                raise
            key = hashlib.sha256(request.action_id.encode("utf-8")).hexdigest()
            durable_unlink(self._prepared_root / f"{key}.json")
            return self._result_from_record(before_count, record)

    def reconcile_prepared_action(
        self, handle: PreparedEffectHandle, context: ExecutionContext
    ) -> ActionReconciliationResult:
        del context
        with self._lock:
            document = self._decode_handle(handle)
            action_id = str(document["action_id"])
            existing = self._find_record(action_id)
            if existing is not None:
                return ActionReconciliationResult(
                    action_id,
                    ActionReconciliationDisposition.APPLIED,
                    self._result_from_record(*existing),
                    {"environment": "alfworld", "source": "durable_action_journal"},
                )
            self._recover_worker()
            current = self.observe(ExecutionContext(run_id="alfworld-reconcile", trace_id="reconcile", span_id="reconcile"))
            result = ActionResult(
                action_id=action_id,
                accepted=False,
                observation=current,
                effect=EffectReceipt(
                    effect_id=f"alfworld-action:{action_id}",
                    request_digest=handle.request_digest,
                    effect_class=EffectClass.RECONCILABLE,
                    certainty=EffectCertainty.NO_EFFECT,
                    provider_instance_id=self.provider_instance_id,
                    verification_required=False,
                    before_artifact=self._generation(),
                    after_artifact=self._generation(),
                    provider_receipt=action_id,
                ),
                diagnostics={"environment": "alfworld", "recovered_from_durable_journal": True},
            )
            return ActionReconciliationResult(
                action_id,
                ActionReconciliationDisposition.NOT_APPLIED,
                result,
                {"environment": "alfworld", "source": "reset_and_replay"},
            )

    def act(self, request: ActionRequest) -> ActionResult:
        handle = self.prepare_action_recovery(request, request.context)
        return self.execute_prepared_action(request, handle)

    def reconcile(self, effect: EffectReceipt, context: ExecutionContext) -> EffectReceipt:
        del context
        with self._lock:
            action_id = effect.provider_receipt or effect.effect_id.removeprefix("alfworld-action:")
            existing = self._find_record(action_id)
            certainty = EffectCertainty.EFFECT_CONFIRMED if existing is not None else EffectCertainty.NO_EFFECT
            return EffectReceipt(
                effect_id=effect.effect_id,
                request_digest=effect.request_digest,
                effect_class=effect.effect_class,
                certainty=certainty,
                provider_instance_id=self.provider_instance_id,
                verification_required=False,
                before_artifact=effect.before_artifact,
                after_artifact=effect.after_artifact if existing is not None else self._generation(),
                provider_receipt=action_id,
            )

    def checkpoint(self) -> bytes:
        with self._lock:
            assert self._state is not None
            return json.dumps(self._state, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def restore(self, payload: bytes) -> None:
        with self._lock:
            raw = json.loads(bytes(payload).decode("utf-8"))
            if not isinstance(raw, dict):
                raise TypeError("ALFWorld checkpoint must decode to an object")
            candidate = dict(raw)
            if candidate.get("schema") != _STATE_SCHEMA:
                raise ValueError("ALFWorld checkpoint schema mismatch")
            if candidate.get("session_id") != self.runtime.session_id:
                raise ValueError("ALFWorld checkpoint session mismatch")
            if candidate.get("task_gamefile") != self.runtime.task_gamefile:
                raise ValueError("ALFWorld checkpoint task mismatch")
            if candidate.get("runtime_artifact_digest") != self.runtime.runtime_artifact_digest:
                raise ValueError("ALFWorld checkpoint runtime mismatch")
            self._persist_state(candidate)
            self._state = candidate
            self._recover_worker()

    def close(self) -> None:
        with self._lock:
            transport, self._transport = self._transport, None
            if transport is None:
                return
            try:
                request_id = self._next_request_id("close")
                transport.send("close", {}, request_id=request_id)
                message = transport.read(timeout_s=min(5.0, self.runtime.command_timeout_s))
                if message.kind != "closed":
                    raise RuntimeError("ALFWorld worker did not acknowledge close")
            finally:
                transport.close()


def build_alfworld_text_session(
    spec: AlfworldTextRuntimeSpec,
    *,
    process_supervisor: ProcessSupervisorPort,
    task_group: TaskGroupPort,
) -> AlfworldTextSession:
    data_root = Path(spec.data_root).resolve(strict=True)
    recovery_root = Path(spec.recovery_root).resolve()
    recovery_root.mkdir(parents=True, exist_ok=True)

    def transport_factory() -> JsonlProcessTransport:
        command = (
            spec.docker_executable,
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,exec,nosuid,size=256m",
            "-v",
            f"{data_root}:{_CONTAINER_DATA_ROOT}:ro",
            spec.image,
            "--data-root",
            _CONTAINER_DATA_ROOT,
            "--config",
            _CONTAINER_CONFIG,
            "--split",
            spec.split,
        )
        return JsonlProcessTransport(
            spec=JsonlProcessSpec(
                command=command,
                cwd=str(data_root),
                stderr_log_path=str(recovery_root / "worker.stderr.log"),
                stdout_queue_capacity=512,
            ),
            operating_system=LocalOperatingSystemRoute(),
            task_group=task_group,
            process_supervisor=process_supervisor,
            transport_identity=spec.provider_instance_id[:20],
            task_namespace="alfworld-worker",
        )

    return AlfworldTextSession(spec, transport_factory=transport_factory)


__all__ = ["AlfworldTextRuntimeSpec", "AlfworldTextSession", "build_alfworld_text_session"]
