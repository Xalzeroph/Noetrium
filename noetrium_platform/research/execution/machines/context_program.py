"""Context projection semantics over the single NoetriumUnit algebra.

Context structure is immutable graph data. Renderer registries and runtime
execution remain behavioral concerns owned by the enclosing RuntimeMachine.
"""
from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import structure_unit

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from noetrium_platform.foundation.kernel.kernel.universal import UnitStepContext, UnitTransition
from noetrium_platform.foundation.kernel.kernel.unit_host import UnitOperationBinding
from .runtime_module import runtime_module
from .domains import RuntimeConcern
from noetrium_platform.foundation.kernel.kernel.universal import unit_operation


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()



def context_block_unit(
    block_id: str,
    renderer: str,
    *,
    priority: int = 0,
    required: bool = False,
    configuration: JsonObject | None = None,
) -> NoetriumUnit:
    block_id = _text(block_id, "context block_id")
    renderer = _text(renderer, "context renderer")
    if type(priority) is not int:
        raise TypeError("context block priority must be an integer")
    if type(required) is not bool:
        raise TypeError("context block required must be boolean")
    if configuration is None:
        configuration = {}
    if not isinstance(configuration, Mapping):
        raise TypeError("context block configuration must be an object")
    return structure_unit(
        block_id,
        traits=(CONTEXT_BLOCK_TRAIT,),
        parameters={
            "renderer": renderer,
            "priority": priority,
            "required": required,
            "configuration": dict(configuration),
        },
    )


def require_context_block(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(CONTEXT_BLOCK_TRAIT):
        raise TypeError("context block must be machine.context.block NoetriumUnit")
    return value


def context_block_renderer(value: NoetriumUnit) -> str:
    return _text(require_context_block(value).parameters["renderer"], "context renderer")


def context_block_priority(value: NoetriumUnit) -> int:
    raw = require_context_block(value).parameters["priority"]
    if type(raw) is not int:
        raise TypeError("context block priority must be integer")
    return raw


def context_block_required(value: NoetriumUnit) -> bool:
    raw = require_context_block(value).parameters["required"]
    if type(raw) is not bool:
        raise TypeError("context block required must be boolean")
    return raw


def context_block_configuration(value: NoetriumUnit) -> Mapping[str, JsonValue]:
    raw = require_context_block(value).parameters.get("configuration", {})
    if not isinstance(raw, Mapping):
        raise TypeError("context block configuration must be object")
    return raw


CONTEXT_GRAPH_TRAIT = "machine.context"
CONTEXT_BLOCK_TRAIT = "machine.context.block"


def context_graph(
    *,
    graph_id: str,
    version: str,
    max_chars: int,
    blocks: tuple[NoetriumUnit, ...],
) -> NoetriumUnit:
    graph_id = _text(graph_id, "context graph_id")
    version = _text(version, "context version")
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("context max_chars must be positive")
    if type(blocks) is not tuple or not blocks:
        raise ValueError("context graph requires at least one block")
    for block in blocks:
        require_context_block(block)
    ids = tuple(block.unit_id for block in blocks)
    if len(ids) != len(set(ids)):
        raise ValueError("context block ids must be unique")
    children = blocks
    return structure_unit(
        graph_id,
        traits=(CONTEXT_GRAPH_TRAIT,),
        parameters={"version": version, "max_chars": max_chars},
        members=children,
    )


def _require_context_graph(graph: NoetriumUnit) -> NoetriumUnit:
    if type(graph) is not NoetriumUnit or not graph.has_trait(CONTEXT_GRAPH_TRAIT):
        raise TypeError("context semantics require machine.context NoetriumUnit")
    return graph


def _context_version(graph: NoetriumUnit) -> str:
    _require_context_graph(graph)
    return _text(graph.parameters.get("version"), "context version")


def _context_max_chars(graph: NoetriumUnit) -> int:
    _require_context_graph(graph)
    value = graph.parameters.get("max_chars")
    if type(value) is not int or value < 1:
        raise ValueError("context graph max_chars must be positive")
    return value


def _context_blocks(graph: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    _require_context_graph(graph)
    rows = tuple(require_context_block(child) for child in graph.members)
    return tuple(
        sorted(
            rows,
            key=lambda block: (-context_block_priority(block), block.unit_id),
        )
    )


@dataclass(frozen=True, slots=True)
class ContextRenderRequest:
    block: NoetriumUnit
    inputs: JsonObject
    available_chars: int

    def __post_init__(self) -> None:
        require_context_block(self.block)
        if not isinstance(self.inputs, Mapping):
            raise TypeError("context render inputs must be an object")
        if type(self.available_chars) is not int or self.available_chars < 0:
            raise ValueError("context render available_chars must be non-negative")
        object.__setattr__(self, "inputs", freeze_json(self.inputs))


@dataclass(frozen=True, slots=True)
class ContextRenderResult:
    text: str
    compacted: bool = False
    receipt: JsonValue = None

    def __post_init__(self) -> None:
        if type(self.text) is not str:
            raise TypeError("context render text must be text")
        if type(self.compacted) is not bool:
            raise TypeError("context render compacted must be boolean")
        object.__setattr__(self, "receipt", freeze_json(self.receipt))


ContextRenderer = Callable[[ContextRenderRequest], ContextRenderResult]


@runtime_checkable
class ContextRendererRegistryPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(self, renderer: str) -> ContextRenderer: ...

    def implementation_digest(self, renderer: str) -> str: ...


class ContextRendererRegistry(ContextRendererRegistryPort):
    def __init__(self) -> None:
        self._renderers: dict[str, tuple[ContextRenderer, str]] = {}
        self._identity_digest_cache: str | None = None
        self._lock = RLock()

    def register(
        self,
        renderer: str,
        handler: ContextRenderer,
        *,
        implementation_digest: str,
    ) -> None:
        renderer = _text(renderer, "context renderer")
        if not callable(handler):
            raise TypeError("context renderer handler must be callable")
        digest = require_sha256(
            implementation_digest,
            "context renderer implementation_digest",
        )
        value = (handler, digest)
        with self._lock:
            current = self._renderers.get(renderer)
            if current is not None and current != value:
                raise ValueError(f"context renderer already registered: {renderer}")
            self._renderers[renderer] = value
            self._identity_digest_cache = None

    def resolve(self, renderer: str) -> ContextRenderer:
        renderer = _text(renderer, "context renderer")
        with self._lock:
            try:
                return self._renderers[renderer][0]
            except KeyError as exc:
                raise KeyError(f"unbound context renderer: {renderer}") from exc

    def implementation_digest(self, renderer: str) -> str:
        renderer = _text(renderer, "context renderer")
        with self._lock:
            try:
                return self._renderers[renderer][1]
            except KeyError as exc:
                raise KeyError(f"unbound context renderer: {renderer}") from exc

    def renderers(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._renderers))

    @property
    def identity_digest(self) -> str:
        with self._lock:
            cached = self._identity_digest_cache
            if cached is None:
                cached = canonical_digest(tuple(
                    (renderer, implementation_digest)
                    for renderer, (_, implementation_digest)
                    in sorted(self._renderers.items())
                ))
                self._identity_digest_cache = cached
            return cached


def context_renderer_binding_digest(
    graph: NoetriumUnit,
    renderers: ContextRendererRegistryPort,
) -> str:
    """Bind context graph semantics to exact referenced renderer code."""

    _require_context_graph(graph)
    if not isinstance(renderers, ContextRendererRegistryPort):
        raise TypeError(
            "context renderer binding requires ContextRendererRegistryPort"
        )
    require_sha256(
        renderers.identity_digest,
        "context renderer registry identity_digest",
    )
    renderer_ids = tuple(sorted({context_block_renderer(block) for block in _context_blocks(graph)}))
    implementations = tuple(
        (
            renderer,
            require_sha256(
                renderers.implementation_digest(renderer),
                "context renderer implementation_digest",
            ),
        )
        for renderer in renderer_ids
    )
    return canonical_digest({
        "context_graph_digest": graph.unit_digest,
        "renderer_implementations": implementations,
    })


class ContextBudgetExceeded(ValueError):
    def __init__(self, *, required_chars: int, max_chars: int) -> None:
        self.required_chars = required_chars
        self.max_chars = max_chars
        super().__init__(
            "required context facts exceed model-view character envelope: "
            f"required={required_chars}, max={max_chars}; required facts are atomic"
        )


@dataclass(frozen=True, slots=True)
class ContextProjection:
    graph_digest: str
    binding_digest: str
    text: str
    block_ids: tuple[str, ...]
    omitted_block_ids: tuple[str, ...]
    compacted_block_ids: tuple[str, ...]
    receipts: JsonObject

    @property
    def lossy(self) -> bool:
        return bool(self.omitted_block_ids or self.compacted_block_ids)


def _envelope(block_id: str, text: str) -> str:
    return f"\n[{block_id}]\n{text}\n"


def compile_context(
    graph: NoetriumUnit,
    inputs: JsonObject,
    renderers: ContextRendererRegistryPort,
) -> ContextProjection:
    _require_context_graph(graph)
    if not isinstance(inputs, Mapping):
        raise TypeError("compile_context inputs must be an object")
    if not isinstance(renderers, ContextRendererRegistryPort):
        raise TypeError("compile_context requires ContextRendererRegistryPort")
    binding_digest = context_renderer_binding_digest(graph, renderers)

    required_rows: list[tuple[NoetriumUnit, ContextRenderResult, str]] = []
    optional_rows: list[NoetriumUnit] = []
    receipts: dict[str, JsonValue] = {}

    max_chars = _context_max_chars(graph)
    for block in _context_blocks(graph):
        if not context_block_required(block):
            optional_rows.append(block)
            continue
        result = renderers.resolve(context_block_renderer(block))(
            ContextRenderRequest(block, inputs, max_chars)
        )
        if not isinstance(result, ContextRenderResult):
            raise TypeError("context renderer must return ContextRenderResult")
        if not result.text:
            raise ValueError(f"required context block rendered empty: {block.unit_id}")
        rendered = _envelope(block.unit_id, result.text)
        required_rows.append((block, result, rendered))
        if result.receipt is not None:
            receipts[block.unit_id] = result.receipt

    required_chars = sum(len(row[2]) for row in required_rows)
    if required_chars > max_chars:
        raise ContextBudgetExceeded(
            required_chars=required_chars,
            max_chars=max_chars,
        )

    rendered = [row[2] for row in required_rows]
    selected = [row[0].block_id for row in required_rows]
    compacted = [row[0].block_id for row in required_rows if row[1].compacted]
    omitted: list[str] = []
    used = required_chars

    for block in optional_rows:
        remaining = max_chars - used
        result = renderers.resolve(context_block_renderer(block))(
            ContextRenderRequest(block, inputs, remaining)
        )
        if not isinstance(result, ContextRenderResult):
            raise TypeError("context renderer must return ContextRenderResult")
        if result.receipt is not None:
            receipts[block.unit_id] = result.receipt
        if not result.text:
            omitted.append(block.unit_id)
            continue
        block_text = _envelope(block.unit_id, result.text)
        if len(block_text) > remaining:
            omitted.append(block.unit_id)
            continue
        rendered.append(block_text)
        selected.append(block.unit_id)
        used += len(block_text)
        if result.compacted:
            compacted.append(block.unit_id)

    text = "".join(rendered)
    if len(text) > max_chars:
        raise RuntimeError("context compiler exceeded hard character budget")
    return ContextProjection(
        graph_digest=graph.unit_digest,
        binding_digest=binding_digest,
        text=text,
        block_ids=tuple(selected),
        omitted_block_ids=tuple(omitted),
        compacted_block_ids=tuple(compacted),
        receipts=freeze_json(receipts),
    )


@dataclass(frozen=True, slots=True)
class ContextRuntimeBinding:
    """Runtime binding for one context graph and its renderers."""

    graph: NoetriumUnit
    renderers: ContextRendererRegistryPort

    def __post_init__(self) -> None:
        _require_context_graph(self.graph)
        if not isinstance(self.renderers, ContextRendererRegistryPort):
            raise TypeError(
                "context runtime binding requires ContextRendererRegistryPort"
            )
        context_renderer_binding_digest(self.graph, self.renderers)

    @property
    def binding_digest(self) -> str:
        return context_renderer_binding_digest(
            self.graph,
            self.renderers,
        )


def context_projection_payload(projection: ContextProjection) -> JsonObject:
    if not isinstance(projection, ContextProjection):
        raise TypeError("context projection payload requires ContextProjection")
    return {
        "context_graph_digest": projection.unit_digest,
        "context_binding_digest": projection.binding_digest,
        "text": projection.text,
        "text_digest": canonical_digest(projection.text),
        "block_ids": projection.block_ids,
        "omitted_block_ids": projection.omitted_block_ids,
        "compacted_block_ids": projection.compacted_block_ids,
        "receipts": projection.receipts,
        "lossy": projection.lossy,
    }


def _runtime_context_project(
    request: UnitStepContext,
    binding: object,
) -> UnitTransition:
    if not isinstance(binding, ContextRuntimeBinding):
        raise TypeError(
            "runtime.context.project requires ContextRuntimeBinding"
        )
    configuration = thaw_json(request.configuration)
    if not isinstance(configuration, dict):
        raise TypeError("runtime context node configuration must be an object")
    expected_digest = configuration.get("context_graph_digest")
    if expected_digest != binding.graph.unit_digest:
        raise ValueError("runtime context graph identity drifted")
    if not isinstance(request.payload, Mapping):
        raise TypeError("runtime context projection payload must be an object")
    payload = thaw_json(request.payload)
    if not isinstance(payload, dict):
        raise TypeError(
            "runtime context projection payload must decode to an object"
        )
    inputs = payload.get("context_inputs")
    if not isinstance(inputs, Mapping):
        raise TypeError(
            "runtime.context.project requires context_inputs object"
        )

    projection = compile_context(
        binding.graph,
        inputs,
        binding.renderers,
    )
    result = context_projection_payload(projection)
    if result["context_binding_digest"] != binding.binding_digest:
        raise RuntimeError("runtime context renderer binding drifted")
    durable_projection = {
        "context_graph_digest": result["context_graph_digest"],
        "context_binding_digest": result["context_binding_digest"],
        "text_digest": result["text_digest"],
        "block_ids": result["block_ids"],
        "omitted_block_ids": result["omitted_block_ids"],
        "compacted_block_ids": result["compacted_block_ids"],
        "receipts": result["receipts"],
        "lossy": result["lossy"],
    }
    return UnitTransition.goto(value=result, state_delta={'last_context_projection': durable_projection}, events=({'type': 'runtime_context_projected', **durable_projection},))


def context_runtime_operation(
    *,
    operation: str = "runtime.context.project",
) -> UnitOperationBinding:
    operation = _text(operation, "runtime context operation")
    return UnitOperationBinding(
        operation,
        _runtime_context_project,
        canonical_digest({
            "operation": operation,
            "implementation_revision": 1,
        }),
    )


def context_runtime_module(
    graph: NoetriumUnit,
    *,
    module_id: str = "runtime.context",
    operation: str = "runtime.context.project",
) -> NoetriumUnit:
    _require_context_graph(graph)
    return runtime_module(
        module_id=module_id,
        concern=RuntimeConcern.CONTEXT,
        entrypoint="project",
        nodes=(
            unit_operation(
                "project",
                operation,
                configuration={
                    "context_graph_id": graph.unit_id,
                    "context_version": _context_version(graph),
                    "context_graph_digest": graph.unit_digest,
                    "max_chars": _context_max_chars(graph),
                },
            ),
        ),
    )


__all__ = [
    "CONTEXT_BLOCK_TRAIT",
    "CONTEXT_GRAPH_TRAIT",
    "context_block_unit",
    "require_context_block",
    "context_block_renderer",
    "context_block_priority",
    "context_block_required",
    "context_block_configuration",
    "context_graph",
    "context_runtime_operation",
    "context_projection_payload",
    "context_renderer_binding_digest",
    "ContextRuntimeBinding",
    "ContextBudgetExceeded",
    "ContextProjection",
    "ContextRenderRequest",
    "ContextRenderResult",
    "ContextRenderer",
    "ContextRendererRegistry",
    "ContextRendererRegistryPort",
    "compile_context",
    "context_runtime_module",
]
