"""Pure ContextProgram IR for model-view/context research semantics.

Context projection is a paper-level runtime concern but does not require its
own durable authority. A ContextProgram is immutable compile-time semantics.
It may be evaluated as a pure projection or referenced by a RuntimeModule,
whose enclosing RuntimeMachine remains the only execution authority.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from .program import ProgramNodeRequest, ProgramNodeResult
from .program_host import ResearchHostOperation
from .runtime_module import RuntimeModule, RuntimeModuleBuilder


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class ContextBlockProgram:
    block_id: str
    renderer: str
    priority: int = 0
    required: bool = False
    configuration: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "block_id", _text(self.block_id, "context block_id"))
        object.__setattr__(self, "renderer", _text(self.renderer, "context renderer"))
        if type(self.priority) is not int:
            raise TypeError("context block priority must be an integer")
        if type(self.required) is not bool:
            raise TypeError("context block required must be boolean")
        if not isinstance(self.configuration, Mapping):
            raise TypeError("context block configuration must be an object")
        object.__setattr__(self, "configuration", freeze_json(self.configuration))


@dataclass(frozen=True, slots=True)
class ContextProgram:
    program_id: str
    version: str
    max_chars: int
    blocks: tuple[ContextBlockProgram, ...]
    program_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", _text(self.program_id, "context program_id"))
        object.__setattr__(self, "version", _text(self.version, "context program version"))
        if type(self.max_chars) is not int or self.max_chars < 1:
            raise ValueError("context program max_chars must be positive")
        if type(self.blocks) is not tuple or not self.blocks:
            raise ValueError("context program requires at least one block")
        if any(not isinstance(block, ContextBlockProgram) for block in self.blocks):
            raise TypeError("context program blocks must be ContextBlockProgram values")
        ids = tuple(block.block_id for block in self.blocks)
        if len(ids) != len(set(ids)):
            raise ValueError("context program block ids must be unique")
        object.__setattr__(
            self,
            "program_digest",
            canonical_digest({
                "program_id": self.program_id,
                "version": self.version,
                "max_chars": self.max_chars,
                "blocks": tuple({
                    "block_id": block.block_id,
                    "renderer": block.renderer,
                    "priority": block.priority,
                    "required": block.required,
                    "configuration": thaw_json(block.configuration),
                } for block in self.blocks),
            }),
        )

    @property
    def ordered_blocks(self) -> tuple[ContextBlockProgram, ...]:
        return tuple(sorted(self.blocks, key=lambda block: (-block.priority, block.block_id)))


@dataclass(frozen=True, slots=True)
class ContextRenderRequest:
    block: ContextBlockProgram
    inputs: JsonObject
    available_chars: int

    def __post_init__(self) -> None:
        if not isinstance(self.block, ContextBlockProgram):
            raise TypeError("context render request requires ContextBlockProgram")
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
            return canonical_digest(tuple(
                (renderer, implementation_digest)
                for renderer, (_, implementation_digest)
                in sorted(self._renderers.items())
            ))


def context_renderer_binding_digest(
    program: ContextProgram,
    renderers: ContextRendererRegistryPort,
) -> str:
    """Bind pure ContextProgram semantics to exact referenced renderer code."""

    if not isinstance(program, ContextProgram):
        raise TypeError(
            "context renderer binding requires ContextProgram"
        )
    if not isinstance(renderers, ContextRendererRegistryPort):
        raise TypeError(
            "context renderer binding requires ContextRendererRegistryPort"
        )
    require_sha256(
        renderers.identity_digest,
        "context renderer registry identity_digest",
    )
    renderer_ids = tuple(sorted({block.renderer for block in program.blocks}))
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
        "context_program_digest": program.program_digest,
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
    program_digest: str
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
    program: ContextProgram,
    inputs: JsonObject,
    renderers: ContextRendererRegistryPort,
) -> ContextProjection:
    if not isinstance(program, ContextProgram):
        raise TypeError("compile_context requires ContextProgram")
    if not isinstance(inputs, Mapping):
        raise TypeError("compile_context inputs must be an object")
    if not isinstance(renderers, ContextRendererRegistryPort):
        raise TypeError("compile_context requires ContextRendererRegistryPort")
    binding_digest = context_renderer_binding_digest(program, renderers)

    required_rows: list[tuple[ContextBlockProgram, ContextRenderResult, str]] = []
    optional_rows: list[ContextBlockProgram] = []
    receipts: dict[str, JsonValue] = {}

    for block in program.ordered_blocks:
        if not block.required:
            optional_rows.append(block)
            continue
        result = renderers.resolve(block.renderer)(
            ContextRenderRequest(block, inputs, program.max_chars)
        )
        if not isinstance(result, ContextRenderResult):
            raise TypeError("context renderer must return ContextRenderResult")
        if not result.text:
            raise ValueError(f"required context block rendered empty: {block.block_id}")
        rendered = _envelope(block.block_id, result.text)
        required_rows.append((block, result, rendered))
        if result.receipt is not None:
            receipts[block.block_id] = result.receipt

    required_chars = sum(len(row[2]) for row in required_rows)
    if required_chars > program.max_chars:
        raise ContextBudgetExceeded(
            required_chars=required_chars,
            max_chars=program.max_chars,
        )

    rendered = [row[2] for row in required_rows]
    selected = [row[0].block_id for row in required_rows]
    compacted = [row[0].block_id for row in required_rows if row[1].compacted]
    omitted: list[str] = []
    used = required_chars

    for block in optional_rows:
        remaining = program.max_chars - used
        result = renderers.resolve(block.renderer)(
            ContextRenderRequest(block, inputs, remaining)
        )
        if not isinstance(result, ContextRenderResult):
            raise TypeError("context renderer must return ContextRenderResult")
        if result.receipt is not None:
            receipts[block.block_id] = result.receipt
        if not result.text:
            omitted.append(block.block_id)
            continue
        block_text = _envelope(block.block_id, result.text)
        if len(block_text) > remaining:
            omitted.append(block.block_id)
            continue
        rendered.append(block_text)
        selected.append(block.block_id)
        used += len(block_text)
        if result.compacted:
            compacted.append(block.block_id)

    text = "".join(rendered)
    if len(text) > program.max_chars:
        raise RuntimeError("context compiler exceeded hard character budget")
    return ContextProjection(
        program_digest=program.program_digest,
        binding_digest=binding_digest,
        text=text,
        block_ids=tuple(selected),
        omitted_block_ids=tuple(omitted),
        compacted_block_ids=tuple(compacted),
        receipts=freeze_json(receipts),
    )


@dataclass(frozen=True, slots=True)
class ContextRuntimeBinding:
    """Runtime binding for one pure ContextProgram and its renderers."""

    program: ContextProgram
    renderers: ContextRendererRegistryPort

    def __post_init__(self) -> None:
        if not isinstance(self.program, ContextProgram):
            raise TypeError("context runtime binding requires ContextProgram")
        if not isinstance(self.renderers, ContextRendererRegistryPort):
            raise TypeError(
                "context runtime binding requires ContextRendererRegistryPort"
            )
        context_renderer_binding_digest(self.program, self.renderers)

    @property
    def binding_digest(self) -> str:
        return context_renderer_binding_digest(
            self.program,
            self.renderers,
        )


def context_projection_payload(projection: ContextProjection) -> JsonObject:
    if not isinstance(projection, ContextProjection):
        raise TypeError("context projection payload requires ContextProjection")
    return {
        "context_program_digest": projection.program_digest,
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
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, ContextRuntimeBinding):
        raise TypeError(
            "runtime.context.project requires ContextRuntimeBinding"
        )
    configuration = thaw_json(request.node.configuration)
    if not isinstance(configuration, dict):
        raise TypeError("runtime context node configuration must be an object")
    expected_digest = configuration.get("context_program_digest")
    if expected_digest != binding.program.program_digest:
        raise ValueError("runtime ContextProgram identity drifted")
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
        binding.program,
        inputs,
        binding.renderers,
    )
    result = context_projection_payload(projection)
    if result["context_binding_digest"] != binding.binding_digest:
        raise RuntimeError("runtime ContextProgram renderer binding drifted")
    durable_projection = {
        "context_program_digest": result["context_program_digest"],
        "context_binding_digest": result["context_binding_digest"],
        "text_digest": result["text_digest"],
        "block_ids": result["block_ids"],
        "omitted_block_ids": result["omitted_block_ids"],
        "compacted_block_ids": result["compacted_block_ids"],
        "receipts": result["receipts"],
        "lossy": result["lossy"],
    }
    return ProgramNodeResult(
        value=result,
        state_update={"last_context_projection": durable_projection},
        events=({
            "type": "runtime_context_projected",
            **durable_projection,
        },),
    )


def context_runtime_operation(
    *,
    operation: str = "runtime.context.project",
) -> ResearchHostOperation:
    operation = _text(operation, "runtime context operation")
    return ResearchHostOperation(
        operation,
        _runtime_context_project,
        canonical_digest({
            "operation": operation,
            "implementation_revision": 1,
        }),
    )


def context_runtime_module(
    program: ContextProgram,
    *,
    module_id: str = "runtime.context",
    operation: str = "runtime.context.project",
) -> RuntimeModule:
    if not isinstance(program, ContextProgram):
        raise TypeError("context runtime module requires ContextProgram")
    return (
        RuntimeModuleBuilder.context(module_id=module_id, entrypoint="project")
        .node(
            "project",
            operation,
            configuration={
                "context_program_id": program.program_id,
                "context_program_version": program.version,
                "context_program_digest": program.program_digest,
                "max_chars": program.max_chars,
            },
        )
        .build()
    )


__all__ = [
    "context_runtime_operation",
    "context_projection_payload",
    "context_renderer_binding_digest",
    "ContextRuntimeBinding",
    "ContextBlockProgram",
    "ContextBudgetExceeded",
    "ContextProgram",
    "ContextProjection",
    "ContextRenderRequest",
    "ContextRenderResult",
    "ContextRenderer",
    "ContextRendererRegistry",
    "ContextRendererRegistryPort",
    "compile_context",
    "context_runtime_module",
]
