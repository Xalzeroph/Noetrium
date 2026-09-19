from __future__ import annotations

import ast
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
)

from .source import CODE_AS_POLICIES_AUDITED_COMMIT


SYNTHESIS_AGENT_ID = "code-as-policies.hierarchical-synthesizer"


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be text")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a sequence")
    rows = tuple(_text(item, field_name) for item in value)
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field_name} must contain unique values")
    return rows


@dataclass(frozen=True, slots=True)
class CodeAsPoliciesFunctionCall:
    function_name: str
    signature: str
    assignment_signature: bool
    call_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "function_name",
            _text(self.function_name, "Code as Policies function_name"),
        )
        object.__setattr__(
            self,
            "signature",
            _text(self.signature, "Code as Policies function signature"),
        )
        if type(self.assignment_signature) is not bool:
            raise TypeError(
                "Code as Policies assignment_signature must be boolean"
            )
        object.__setattr__(
            self,
            "call_digest",
            canonical_digest({
                "function_name": self.function_name,
                "signature": self.signature,
                "assignment_signature": self.assignment_signature,
            }),
        )


class _FunctionParser(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: OrderedDict[str, str] = OrderedDict()
        self.assignments: OrderedDict[str, str] = OrderedDict()

    def visit_Call(self, node: ast.Call) -> None:
        self.generic_visit(node)
        if isinstance(node.func, ast.Name):
            self.calls[node.func.id] = ast.unparse(node).strip()

    def visit_Assign(self, node: ast.Assign) -> None:
        self.generic_visit(node)
        if isinstance(node.value, ast.Call) and isinstance(
            node.value.func,
            ast.Name,
        ):
            self.assignments[node.value.func.id] = ast.unparse(node).strip()


def discover_function_calls(
    source: str,
) -> tuple[CodeAsPoliciesFunctionCall, ...]:
    """Reproduce the paper-era FunctionParser call/signature semantics."""

    source = _text(source, "Code as Policies source", allow_empty=True)
    tree = ast.parse(source)
    parser = _FunctionParser()
    parser.visit(tree)
    calls = OrderedDict(parser.calls)
    for name, assignment in parser.assignments.items():
        if name in calls:
            calls[name] = assignment
    return tuple(
        CodeAsPoliciesFunctionCall(
            function_name=name,
            signature=signature,
            assignment_signature=name in parser.assignments,
        )
        for name, signature in calls.items()
    )


def function_body_source(
    source: str,
    *,
    expected_name: str,
) -> str:
    """Return the first generated function body exactly as recursion consumes it."""

    tree = ast.parse(_text(source, "Code as Policies helper source"))
    if not tree.body or not isinstance(
        tree.body[0],
        (ast.FunctionDef, ast.AsyncFunctionDef),
    ):
        raise ValueError(
            "Code as Policies generated helper must start with a function"
        )
    function = tree.body[0]
    if function.name != expected_name:
        raise ValueError(
            "Code as Policies generated helper name does not match signature"
        )
    if not function.body:
        raise ValueError("Code as Policies generated helper has empty body")
    return "\n".join(ast.unparse(node) for node in function.body)


class CodeAsPoliciesGenerationKind(StrEnum):
    POLICY = "policy"
    FUNCTION = "function"


@dataclass(frozen=True, slots=True)
class CodeAsPoliciesGenerationRequest:
    kind: CodeAsPoliciesGenerationKind
    query: str
    context: str
    function_name: str | None = None
    function_signature: str | None = None
    parent_function: str | None = None
    depth: int = 0
    known_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CodeAsPoliciesGenerationKind):
            raise TypeError("Code as Policies generation kind is invalid")
        object.__setattr__(
            self,
            "query",
            _text(self.query, "Code as Policies generation query"),
        )
        object.__setattr__(
            self,
            "context",
            _text(
                self.context,
                "Code as Policies generation context",
                allow_empty=True,
            ),
        )
        if type(self.depth) is not int or self.depth < 0:
            raise ValueError(
                "Code as Policies generation depth must be non-negative"
            )
        object.__setattr__(
            self,
            "known_names",
            _strings(self.known_names, "Code as Policies known_names"),
        )
        if self.kind is CodeAsPoliciesGenerationKind.POLICY:
            if self.function_name is not None or self.function_signature is not None:
                raise ValueError(
                    "policy generation cannot carry a function signature"
                )
        else:
            object.__setattr__(
                self,
                "function_name",
                _text(
                    self.function_name,
                    "Code as Policies function_name",
                ),
            )
            object.__setattr__(
                self,
                "function_signature",
                _text(
                    self.function_signature,
                    "Code as Policies function_signature",
                ),
            )
        if self.parent_function is not None:
            object.__setattr__(
                self,
                "parent_function",
                _text(
                    self.parent_function,
                    "Code as Policies parent_function",
                ),
            )


@dataclass(frozen=True, slots=True)
class CodeAsPoliciesGeneration:
    source: str
    model_receipt: JsonValue = None
    generation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source",
            _text(self.source, "Code as Policies generated source"),
        )
        object.__setattr__(
            self,
            "model_receipt",
            freeze_json(self.model_receipt),
        )
        object.__setattr__(
            self,
            "generation_digest",
            canonical_digest({
                "source": self.source,
                "model_receipt": thaw_json(self.model_receipt),
            }),
        )


@runtime_checkable
class CodeAsPoliciesGeneratorPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def generate(
        self,
        request: CodeAsPoliciesGenerationRequest,
        context: ExecutionContext,
    ) -> CodeAsPoliciesGeneration: ...


@dataclass(frozen=True, slots=True)
class CodeAsPoliciesHelperSource:
    function_name: str
    signature: str
    source: str
    parent_function: str | None
    depth: int
    source_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "function_name",
            _text(self.function_name, "Code as Policies helper name"),
        )
        object.__setattr__(
            self,
            "signature",
            _text(self.signature, "Code as Policies helper signature"),
        )
        object.__setattr__(
            self,
            "source",
            _text(self.source, "Code as Policies helper source"),
        )
        if self.parent_function is not None:
            object.__setattr__(
                self,
                "parent_function",
                _text(
                    self.parent_function,
                    "Code as Policies helper parent",
                ),
            )
        if type(self.depth) is not int or self.depth < 1:
            raise ValueError("Code as Policies helper depth must be positive")
        object.__setattr__(
            self,
            "source_digest",
            canonical_digest({
                "function_name": self.function_name,
                "signature": self.signature,
                "source": self.source,
                "parent_function": self.parent_function,
                "depth": self.depth,
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "function_name": self.function_name,
            "signature": self.signature,
            "source": self.source,
            "parent_function": self.parent_function,
            "depth": self.depth,
            "source_digest": self.source_digest,
        }


@dataclass(frozen=True, slots=True)
class CodeAsPoliciesSynthesisBundle:
    query: str
    context: str
    policy_source: str
    helper_sources: tuple[CodeAsPoliciesHelperSource, ...]
    generation_receipts: tuple[JsonObject, ...]
    bundle_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "query",
            _text(self.query, "Code as Policies bundle query"),
        )
        object.__setattr__(
            self,
            "context",
            _text(
                self.context,
                "Code as Policies bundle context",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "policy_source",
            _text(
                self.policy_source,
                "Code as Policies policy source",
            ),
        )
        if type(self.helper_sources) is not tuple or any(
            not isinstance(item, CodeAsPoliciesHelperSource)
            for item in self.helper_sources
        ):
            raise TypeError(
                "Code as Policies helper_sources must be typed tuple"
            )
        if type(self.generation_receipts) is not tuple or any(
            not isinstance(item, Mapping)
            for item in self.generation_receipts
        ):
            raise TypeError(
                "Code as Policies generation_receipts must be object tuple"
            )
        object.__setattr__(
            self,
            "generation_receipts",
            tuple(freeze_json(item) for item in self.generation_receipts),
        )
        object.__setattr__(
            self,
            "bundle_digest",
            canonical_digest({
                "query": self.query,
                "context": self.context,
                "policy_source": self.policy_source,
                "helper_source_digests": tuple(
                    item.source_digest for item in self.helper_sources
                ),
                "generation_receipts": tuple(
                    thaw_json(item) for item in self.generation_receipts
                ),
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "query": self.query,
            "context": self.context,
            "policy_source": self.policy_source,
            "helper_sources": tuple(
                item.payload() for item in self.helper_sources
            ),
            "generation_receipts": tuple(
                thaw_json(item) for item in self.generation_receipts
            ),
            "bundle_digest": self.bundle_digest,
        }


class CodeAsPoliciesHierarchicalSynthesisAgentLoop:
    """Paper-owned hierarchical source synthesis; performs no code execution."""

    def __init__(
        self,
        generator: CodeAsPoliciesGeneratorPort,
        *,
        max_depth: int = 64,
        max_helpers: int = 256,
    ) -> None:
        if not isinstance(generator, CodeAsPoliciesGeneratorPort):
            raise TypeError(
                "Code as Policies synthesis requires generator port"
            )
        require_sha256(
            generator.identity_digest,
            "Code as Policies generator identity_digest",
        )
        if type(max_depth) is not int or max_depth < 1:
            raise ValueError("Code as Policies max_depth must be positive")
        if type(max_helpers) is not int or max_helpers < 1:
            raise ValueError("Code as Policies max_helpers must be positive")
        self._generator = generator
        self._max_depth = max_depth
        self._max_helpers = max_helpers

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "agent_id": SYNTHESIS_AGENT_ID,
            "source_commit": CODE_AS_POLICIES_AUDITED_COMMIT,
            "generator_identity_digest": self._generator.identity_digest,
            "max_depth": self._max_depth,
            "max_helpers": self._max_helpers,
            "implementation_revision": 1,
        })

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if request.agent_id != SYNTHESIS_AGENT_ID:
            raise ValueError(
                f"unexpected Code as Policies agent id: {request.agent_id}"
            )
        view = thaw_json(request.view)
        if not isinstance(view, dict):
            raise TypeError("Code as Policies synthesis view must be object")
        query = _text(view.get("query"), "Code as Policies query")
        context = _text(
            view.get("context", ""),
            "Code as Policies context",
            allow_empty=True,
        )
        known_names = _strings(
            view.get("known_names", ()),
            "Code as Policies known_names",
        )
        known = set(known_names)

        receipts: list[JsonObject] = []
        helpers: OrderedDict[str, CodeAsPoliciesHelperSource] = OrderedDict()
        active: list[str] = []

        policy = self._generator.generate(
            CodeAsPoliciesGenerationRequest(
                kind=CodeAsPoliciesGenerationKind.POLICY,
                query=query,
                context=context,
                depth=0,
                known_names=known_names,
            ),
            request.context,
        )
        if not isinstance(policy, CodeAsPoliciesGeneration):
            raise TypeError(
                "Code as Policies generator must return typed generation"
            )
        receipts.append({
            "kind": CodeAsPoliciesGenerationKind.POLICY.value,
            "function_name": None,
            "parent_function": None,
            "depth": 0,
            "generation_digest": policy.generation_digest,
            "source_digest": canonical_digest(policy.source),
            "model_receipt": thaw_json(policy.model_receipt),
        })

        def expand(source: str, *, parent: str | None, depth: int) -> None:
            if depth > self._max_depth:
                raise RuntimeError(
                    "Code as Policies helper recursion exceeded safety budget"
                )
            for call in discover_function_calls(source):
                name = call.function_name
                if name in known or name in helpers:
                    continue
                if name in active:
                    raise RuntimeError(
                        "Code as Policies generated cyclic helper dependency: "
                        + " -> ".join((*active, name))
                    )
                if len(helpers) + len(active) >= self._max_helpers:
                    raise RuntimeError(
                        "Code as Policies helper count exceeded safety budget"
                    )
                active.append(name)
                generated = self._generator.generate(
                    CodeAsPoliciesGenerationRequest(
                        kind=CodeAsPoliciesGenerationKind.FUNCTION,
                        query=query,
                        context=context,
                        function_name=name,
                        function_signature=call.signature,
                        parent_function=parent,
                        depth=depth,
                        known_names=tuple(
                            sorted(known | set(helpers) | set(active[:-1]))
                        ),
                    ),
                    request.context,
                )
                if not isinstance(generated, CodeAsPoliciesGeneration):
                    raise TypeError(
                        "Code as Policies generator returned invalid helper"
                    )
                receipts.append({
                    "kind": CodeAsPoliciesGenerationKind.FUNCTION.value,
                    "function_name": name,
                    "function_signature": call.signature,
                    "parent_function": parent,
                    "depth": depth,
                    "generation_digest": generated.generation_digest,
                    "source_digest": canonical_digest(generated.source),
                    "model_receipt": thaw_json(generated.model_receipt),
                })
                body = function_body_source(
                    generated.source,
                    expected_name=name,
                )
                expand(body, parent=name, depth=depth + 1)
                active.pop()
                helpers[name] = CodeAsPoliciesHelperSource(
                    function_name=name,
                    signature=call.signature,
                    source=generated.source,
                    parent_function=parent,
                    depth=depth,
                )

        expand(policy.source, parent=None, depth=1)
        bundle = CodeAsPoliciesSynthesisBundle(
            query=query,
            context=context,
            policy_source=policy.source,
            helper_sources=tuple(helpers.values()),
            generation_receipts=tuple(receipts),
        )
        return MethodAgentResult(
            value=bundle.payload(),
            state_update={
                "policy_source": bundle.policy_source,
                "helper_sources": tuple(
                    item.payload() for item in bundle.helper_sources
                ),
                "generation_receipts": bundle.generation_receipts,
                "synthesis_bundle_digest": bundle.bundle_digest,
                "synthesis_complete": True,
            },
        )


__all__ = [
    "SYNTHESIS_AGENT_ID",
    "CodeAsPoliciesFunctionCall",
    "CodeAsPoliciesGeneration",
    "CodeAsPoliciesGenerationKind",
    "CodeAsPoliciesGenerationRequest",
    "CodeAsPoliciesGeneratorPort",
    "CodeAsPoliciesHelperSource",
    "CodeAsPoliciesHierarchicalSynthesisAgentLoop",
    "CodeAsPoliciesSynthesisBundle",
    "discover_function_calls",
    "function_body_source",
]
