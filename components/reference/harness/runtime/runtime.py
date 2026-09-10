"""Deterministic Harness runtime with explicit plugin and node lifecycles."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock
from typing import Any

from noetrium.contracts.json import JsonValue, canonical_digest, freeze_json

from ..api import (
    HarnessNodePort,
    HarnessNodeResult,
    HarnessNodeSpec,
    HarnessPluginSpec,
    HarnessProfile,
    HarnessProfileMode,
)


class HarnessError(RuntimeError):
    pass


class HarnessProfileFrozenError(HarnessError):
    pass


class HarnessDependencyError(HarnessError):
    pass


class HarnessServiceMissingError(HarnessError):
    pass


class HarnessLifecycleError(HarnessError):
    pass


class HarnessNodeExecutionError(HarnessError):
    def __init__(self, node_id: str, cause: Exception) -> None:
        self.node_id = node_id
        self.cause = cause
        super().__init__(f"harness node {node_id!r} failed: {type(cause).__name__}: {cause}")


class HarnessRunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class HarnessLifecycleEvent:
    event_type: str
    profile_digest: str
    subject: str
    payload: Mapping[str, JsonValue] = field(default_factory=dict)
    event_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.event_type) is not str or not self.event_type.strip():
            raise ValueError("harness event_type must be non-empty")
        if type(self.profile_digest) is not str or len(self.profile_digest) != 64:
            raise ValueError("harness profile_digest must be SHA-256")
        if type(self.subject) is not str or not self.subject.strip():
            raise ValueError("harness event subject must be non-empty")
        frozen = freeze_json(self.payload)
        object.__setattr__(self, "payload", frozen)
        object.__setattr__(self, "event_digest", canonical_digest({
            "event_type": self.event_type,
            "profile_digest": self.profile_digest,
            "subject": self.subject,
            "payload": frozen,
        }))


@dataclass(frozen=True, slots=True)
class HarnessRunResult:
    status: HarnessRunStatus
    profile: HarnessProfile
    state: Mapping[str, JsonValue]
    node_results: tuple[HarnessNodeResult, ...] = ()
    events: tuple[HarnessLifecycleEvent, ...] = ()
    error: str | None = None
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, HarnessRunStatus):
            raise TypeError("harness run status is invalid")
        if type(self.profile) is not HarnessProfile:
            raise TypeError("harness run profile is invalid")
        object.__setattr__(self, "state", freeze_json(self.state))
        if type(self.node_results) is not tuple or any(type(item) is not HarnessNodeResult for item in self.node_results):
            raise TypeError("harness node_results are invalid")
        if type(self.events) is not tuple or any(type(item) is not HarnessLifecycleEvent for item in self.events):
            raise TypeError("harness events are invalid")
        if self.error is not None and type(self.error) is not str:
            raise TypeError("harness run error must be string or None")
        object.__setattr__(self, "result_digest", canonical_digest({
            "status": self.status.value,
            "profile_digest": self.profile.profile_digest,
            "state": self.state,
            "node_results": tuple(item.result_digest for item in self.node_results),
            "events": tuple(item.event_digest for item in self.events),
            "error": self.error,
        }))


class HarnessContext:
    """Mutable service container scoped to exactly one started profile."""

    def __init__(self, profile: HarnessProfile) -> None:
        self.profile = profile
        self._services: dict[str, object] = {}
        self._lock = RLock()

    def provide(self, key: str, service: object) -> None:
        if type(key) is not str or not key.strip():
            raise ValueError("harness service key must be non-empty")
        if service is None:
            raise ValueError("harness service cannot be None")
        with self._lock:
            if key in self._services:
                raise HarnessError(f"harness service already provided: {key}")
            self._services[key] = service

    def require(self, key: str, expected_type: type[Any] | None = None) -> object:
        with self._lock:
            if key not in self._services:
                raise HarnessServiceMissingError(f"harness service is not installed: {key}")
            service = self._services[key]
        if expected_type is not None and not isinstance(service, expected_type):
            raise TypeError(f"harness service {key!r} is not {expected_type.__name__}")
        return service

    def services(self) -> Mapping[str, object]:
        with self._lock:
            return dict(self._services)


@dataclass(frozen=True, slots=True)
class _PluginBinding:
    spec: HarnessPluginSpec
    factory: Callable[[HarnessContext], object | None]


@dataclass(frozen=True, slots=True)
class _NodeBinding:
    spec: HarnessNodeSpec
    factory: Callable[[HarnessContext], HarnessNodePort]


def _topological(items: tuple[Any, ...], label: str) -> tuple[Any, ...]:
    by_id = {item.plugin_id if isinstance(item, HarnessPluginSpec) else item.node_id: item for item in items}
    remaining = set(by_id)
    ordered: list[Any] = []
    while remaining:
        ready = sorted(
            identifier for identifier in remaining
            if all(dependency not in remaining for dependency in (
                by_id[identifier].depends_on
            ))
        )
        if not ready:
            raise HarnessDependencyError(f"circular {label} dependency: {sorted(remaining)}")
        ordered.extend(by_id[identifier] for identifier in ready)
        remaining.difference_update(ready)
    return tuple(ordered)


class HarnessRuntime:
    """Composition root for a replaceable research method and its platform services.

    Registration is open in workbench mode until compilation. A study profile
    freezes plugin/node identities and dependency order before execution.
    """

    def __init__(self, *, mode: HarnessProfileMode = HarnessProfileMode.WORKBENCH) -> None:
        if not isinstance(mode, HarnessProfileMode):
            raise TypeError("harness mode must be HarnessProfileMode")
        self.mode = mode
        self._plugins: dict[str, _PluginBinding] = {}
        self._nodes: dict[str, _NodeBinding] = {}
        self._compiled: HarnessProfile | None = None
        self._context: HarnessContext | None = None
        self._disposers: list[Callable[[], object]] = []
        self._node_instances: dict[str, HarnessNodePort] = {}
        self._events: list[HarnessLifecycleEvent] = []
        self._lock = RLock()

    @property
    def profile(self) -> HarnessProfile | None:
        return self._compiled

    @property
    def context(self) -> HarnessContext:
        if self._context is None:
            raise HarnessLifecycleError("harness runtime is not started")
        return self._context

    @property
    def events(self) -> tuple[HarnessLifecycleEvent, ...]:
        return tuple(self._events)

    def _ensure_editable(self) -> None:
        if self._compiled is not None:
            raise HarnessProfileFrozenError("harness profile is already compiled and frozen")
        if self._context is not None:
            raise HarnessLifecycleError("close the started harness before changing registration")

    def register_plugin(
        self,
        spec: HarnessPluginSpec,
        factory: Callable[[HarnessContext], object | None],
        *,
        replace: bool = False,
    ) -> None:
        if type(spec) is not HarnessPluginSpec or not callable(factory):
            raise TypeError("harness plugin registration is invalid")
        with self._lock:
            self._ensure_editable()
            if spec.plugin_id in self._plugins and not replace:
                raise HarnessError(f"harness plugin already registered: {spec.plugin_id}")
            self._plugins[spec.plugin_id] = _PluginBinding(spec, factory)

    def register_node(
        self,
        spec: HarnessNodeSpec,
        factory: Callable[[HarnessContext], HarnessNodePort],
        *,
        replace: bool = False,
    ) -> None:
        if type(spec) is not HarnessNodeSpec or not callable(factory):
            raise TypeError("harness node registration is invalid")
        with self._lock:
            self._ensure_editable()
            if spec.node_id in self._nodes and not replace:
                raise HarnessError(f"harness node already registered: {spec.node_id}")
            self._nodes[spec.node_id] = _NodeBinding(spec, factory)

    def compile(self, profile_id: str, *, mode: HarnessProfileMode | None = None) -> HarnessProfile:
        with self._lock:
            self._ensure_editable()
            selected_mode = self.mode if mode is None else mode
            if not isinstance(selected_mode, HarnessProfileMode):
                raise TypeError("harness profile mode is invalid")
            plugins = _topological(tuple(binding.spec for binding in self._plugins.values()), "plugin")
            nodes = _topological(tuple(binding.spec for binding in self._nodes.values()), "node")
            providers: dict[str, str] = {}
            for plugin in plugins:
                for key in plugin.services:
                    if key in providers:
                        raise HarnessDependencyError(
                            f"service {key!r} is provided by both {providers[key]!r} and {plugin.plugin_id!r}"
                        )
                    providers[key] = plugin.plugin_id
            for node in nodes:
                missing = tuple(key for key in node.service_keys if key not in providers)
                if missing:
                    raise HarnessServiceMissingError(
                        f"node {node.node_id!r} requires undeclared services: {missing}"
                    )
            profile = HarnessProfile(
                profile_id,
                selected_mode,
                plugins=plugins,
                nodes=nodes,
            )
            self._compiled = profile
            return profile

    def _record(self, event_type: str, subject: str, payload: Mapping[str, JsonValue] | None = None) -> None:
        profile = self._compiled
        if profile is None:
            return
        self._events.append(HarnessLifecycleEvent(
            event_type,
            profile.profile_digest,
            subject,
            {} if payload is None else payload,
        ))

    @staticmethod
    def _disposer(installed: object | None) -> Callable[[], object]:
        if installed is None:
            return lambda: None
        dispose = getattr(installed, "dispose", None)
        if callable(dispose):
            return dispose
        if callable(installed):
            return installed
        return lambda: None

    def start(self, profile: HarnessProfile | None = None) -> HarnessProfile:
        with self._lock:
            if self._context is not None:
                raise HarnessLifecycleError("harness runtime is already started")
            if self._compiled is None:
                if profile is None:
                    raise HarnessLifecycleError("compile a harness profile before start")
                self._compiled = profile
            elif profile is not None and profile.profile_digest != self._compiled.profile_digest:
                raise HarnessProfileFrozenError("requested profile differs from compiled profile")
            active = self._compiled
            assert active is not None
            self._context = HarnessContext(active)
            try:
                for spec in active.plugins:
                    binding = self._plugins.get(spec.plugin_id)
                    if binding is None or binding.spec.plugin_digest != spec.plugin_digest:
                        raise HarnessProfileFrozenError(f"plugin binding changed: {spec.plugin_id}")
                    installed = binding.factory(self._context)
                    self._disposers.append(self._disposer(installed))
                    self._record("plugin_installed", spec.plugin_id, {"plugin_digest": spec.plugin_digest})
                for spec in active.nodes:
                    binding = self._nodes.get(spec.node_id)
                    if binding is None or binding.spec.node_digest != spec.node_digest:
                        raise HarnessProfileFrozenError(f"node binding changed: {spec.node_id}")
                    instance = binding.factory(self._context)
                    if not hasattr(instance, "run") or not callable(instance.run):
                        raise TypeError(f"harness node {spec.node_id!r} does not expose run")
                    self._node_instances[spec.node_id] = instance
                    self._record("node_bound", spec.node_id, {"node_digest": spec.node_digest})
                self._record("started", active.profile_id, {"mode": active.mode.value})
                return active
            except BaseException:
                self.close()
                raise

    def close(self) -> None:
        with self._lock:
            for dispose in reversed(self._disposers):
                try:
                    dispose()
                except Exception:
                    pass
            self._disposers.clear()
            self._node_instances.clear()
            self._context = None

    def run(self, initial_state: Mapping[str, JsonValue] | None = None) -> HarnessRunResult:
        with self._lock:
            if self._context is None or self._compiled is None:
                raise HarnessLifecycleError("start the harness runtime before run")
            profile = self._compiled
            state: Mapping[str, JsonValue] = {} if initial_state is None else freeze_json(initial_state)
            node_results: list[HarnessNodeResult] = []
            run_events: list[HarnessLifecycleEvent] = []
            try:
                for spec in profile.nodes:
                    node = self._node_instances[spec.node_id]
                    try:
                        outputs = node.run(self._context, state)
                        result = HarnessNodeResult(spec.node_id, outputs)
                    except Exception as exc:
                        raise HarnessNodeExecutionError(spec.node_id, exc) from exc
                    state = freeze_json({**dict(state), **dict(result.outputs)})
                    node_results.append(result)
                    event = HarnessLifecycleEvent(
                        "node_completed",
                        profile.profile_digest,
                        spec.node_id,
                        {"result_digest": result.result_digest, "phase": spec.phase.value},
                    )
                    run_events.append(event)
                    self._events.append(event)
                completed = HarnessLifecycleEvent(
                    "completed", profile.profile_digest, profile.profile_id,
                    {"node_count": len(node_results)},
                )
                run_events.append(completed)
                self._events.append(completed)
                return HarnessRunResult(
                    HarnessRunStatus.COMPLETED,
                    profile,
                    state,
                    tuple(node_results),
                    tuple(run_events),
                )
            except HarnessNodeExecutionError as exc:
                failed = HarnessLifecycleEvent(
                    "failed", profile.profile_digest, exc.node_id,
                    {"error": str(exc)},
                )
                run_events.append(failed)
                self._events.append(failed)
                return HarnessRunResult(
                    HarnessRunStatus.FAILED,
                    profile,
                    state,
                    tuple(node_results),
                    tuple(run_events),
                    error=str(exc),
                )


__all__ = [
    "HarnessContext",
    "HarnessDependencyError",
    "HarnessError",
    "HarnessLifecycleError",
    "HarnessLifecycleEvent",
    "HarnessNodeExecutionError",
    "HarnessProfileFrozenError",
    "HarnessRunResult",
    "HarnessRunStatus",
    "HarnessRuntime",
    "HarnessServiceMissingError",
]
