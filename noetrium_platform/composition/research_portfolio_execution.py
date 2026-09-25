"""Canonical ResearchPortfolio execution composition.

Every authoring/discovery surface eventually produces a ResearchPortfolio.  From
that boundary onward execution is cardinality-agnostic: one program and one
hundred programs use the same authority materialization, preflight, Research OS
composition, execution pool and shutdown path.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.resources.directory.runtime import (
    standard_local_directory_layout,
)
from noetrium_platform.product.research_os import (
    ResearchControlReceipt,
    ResearchExecutionTarget,
    ResearchGraphRevision,
    ResearchPortfolio,
)

from .managed_research_runtime import (
    ManagedResearchRuntime,
    build_local_managed_research_runtime,
)
from .research_execution_content import (
    ResearchExecutionContentAuthorities,
    compose_research_execution_content,
)
from .research_execution_pool import ResearchExecutionPool
from noetrium_platform.research.execution.workflow.api.runtime_binding import (
    MethodRuntimePortInventory,
)

from .research_binding_authority import ResearchBindingAuthorityPort
from .research_os_experiment import ResearchOSExperimentClosurePort
from .research_os_experiment_runtime_binding import (
    ResearchOSExperimentRuntimeComponents,
)
from .research_os_local import compose_local_research_os
from .research_os_study_closure import ResearchStudyProtocolClosureProvider


def _require_sha256(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class ResearchExecutionAuthorities:
    """Complete execution authority bundle for one frozen ResearchPortfolio."""

    authority_manifest_digest: str
    experiment_closures: ResearchOSExperimentClosurePort | None = None
    experiment_runtime_components: ResearchOSExperimentRuntimeComponents | None = None
    method_runtime_inventory: MethodRuntimePortInventory | None = None

    def __post_init__(self) -> None:
        _require_sha256(
            self.authority_manifest_digest,
            "research execution authority_manifest_digest",
        )
        if (self.experiment_closures is None) != (
            self.experiment_runtime_components is None
        ):
            raise ValueError(
                "research execution Experimentation authority requires both "
                "closure resolver and runtime components"
            )
        if self.experiment_closures is not None and not isinstance(
            self.experiment_closures,
            ResearchOSExperimentClosurePort,
        ):
            raise TypeError(
                "research execution experiment_closures must satisfy "
                "ResearchOSExperimentClosurePort"
            )
        if (
            self.experiment_runtime_components is not None
            and type(self.experiment_runtime_components)
            is not ResearchOSExperimentRuntimeComponents
        ):
            raise TypeError(
                "research execution experiment_runtime_components must be typed"
            )
        if self.method_runtime_inventory is not None and not isinstance(
            self.method_runtime_inventory,
            MethodRuntimePortInventory,
        ):
            raise TypeError(
                "research execution method_runtime_inventory must be "
                "MethodRuntimePortInventory"
            )

    @classmethod
    def from_study_bindings(
        cls,
        authority_manifest_digest: str,
        *,
        research_bindings: ResearchBindingAuthorityPort,
        experiment_runtime_components: ResearchOSExperimentRuntimeComponents,
        method_runtime_inventory: MethodRuntimePortInventory | None = None,
    ) -> "ResearchExecutionAuthorities":
        if not isinstance(research_bindings, ResearchBindingAuthorityPort):
            raise TypeError(
                "research execution research_bindings must satisfy "
                "ResearchBindingAuthorityPort"
            )
        return cls(
            authority_manifest_digest,
            ResearchStudyProtocolClosureProvider(research_bindings),
            experiment_runtime_components,
            method_runtime_inventory,
        )

    @classmethod
    def provider_neutral(cls) -> "ResearchExecutionAuthorities":
        return cls(
            canonical_digest(
                {
                    "schema": "noetrium.research-execution-authorities.v1",
                    "mode": "provider-neutral",
                }
            )
        )


@dataclass(frozen=True, slots=True)
class ResearchExecutionContext:
    """Shared physical/runtime authority context for any portfolio cardinality."""

    state_root: Path
    runtime: ManagedResearchRuntime
    content: ResearchExecutionContentAuthorities | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state_root, Path):
            raise TypeError("research execution context state_root must be pathlib.Path")
        if not isinstance(self.runtime, ManagedResearchRuntime):
            raise TypeError(
                "research execution context runtime must be ManagedResearchRuntime"
            )
        if self.content is None:
            object.__setattr__(
                self,
                "content",
                compose_research_execution_content(
                    self.state_root / "content"
                ),
            )
        elif type(self.content) is not ResearchExecutionContentAuthorities:
            raise TypeError(
                "research execution context content must be "
                "ResearchExecutionContentAuthorities"
            )

    @property
    def execution_pool(self) -> ResearchExecutionPool:
        return self.runtime.execution_pool

    @property
    def management(self):
        return self.runtime.management

    @property
    def resources(self):
        return self.runtime.resources

    @property
    def model_replica_pool(self):
        return self.runtime.model_replica_pool


@runtime_checkable
class ResearchExecutionAuthorityMaterializerPort(Protocol):
    """Materialize exact owner authorities for one frozen ResearchPortfolio."""

    def materialize(
        self,
        portfolio: ResearchPortfolio,
    ) -> ResearchExecutionAuthorities: ...


def load_research_execution_authority_materializer(
    spec: str,
    context: ResearchExecutionContext,
) -> ResearchExecutionAuthorityMaterializerPort:
    """Load one public materializer factory for any ResearchPortfolio."""

    if type(spec) is not str or not spec.strip() or spec != spec.strip():
        raise ValueError(
            "research execution authority materializer spec must be canonical text"
        )
    if type(context) is not ResearchExecutionContext:
        raise TypeError(
            "research execution authority materializer requires ResearchExecutionContext"
        )
    module_name, separator, qualname = spec.partition(":")
    if (
        separator != ":"
        or not module_name
        or not qualname
        or ":" in qualname
        or any(not part or part.startswith("_") for part in qualname.split("."))
    ):
        raise ValueError(
            "research execution authority materializer must use public "
            "module:factory format"
        )
    try:
        value: object = importlib.import_module(module_name)
        for part in qualname.split("."):
            value = getattr(value, part)
    except (ImportError, AttributeError) as exc:
        raise ValueError(
            "research execution authority materializer factory cannot be imported: "
            f"{spec}"
        ) from exc
    if not callable(value):
        raise TypeError(
            "research execution authority materializer factory must be callable"
        )
    materializer = value(context)
    if not isinstance(materializer, ResearchExecutionAuthorityMaterializerPort):
        raise TypeError(
            "research execution authority factory must return "
            "ResearchExecutionAuthorityMaterializerPort"
        )
    return materializer


@contextmanager
def open_local_research_execution_context(
    state_root: Path,
    *,
    start_background_controllers: bool,
) -> Iterator[ResearchExecutionContext]:
    """Open the one ManagedResearchRuntime used by a portfolio execution."""

    if not isinstance(state_root, Path):
        raise TypeError("research execution state_root must be pathlib.Path")
    resolved_root = state_root.expanduser().absolute()
    runtime = build_local_managed_research_runtime(
        standard_local_directory_layout(resolved_root / "platform-runtime"),
        start_background_controllers=start_background_controllers,
    )
    context = ResearchExecutionContext(resolved_root, runtime)
    try:
        yield context
    except BaseException as primary:
        try:
            runtime.close()
        except BaseException as cleanup:
            raise ExceptionGroup(
                "research execution and runtime shutdown failed",
                [primary, cleanup],
            )
        raise
    else:
        runtime.close()


@dataclass(frozen=True, slots=True)
class ResearchPortfolioPreflightResult:
    portfolio_id: str
    portfolio_digest: str
    authority_manifest_digest: str
    execution_id: str
    revision_digest: str
    selected_node_ids: tuple[str, ...]
    admission_digests: tuple[str, ...]
    preflight_digest: str
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "portfolio_digest",
            "authority_manifest_digest",
            "revision_digest",
            "preflight_digest",
        ):
            _require_sha256(
                getattr(self, field_name),
                f"research portfolio preflight {field_name}",
            )
        object.__setattr__(
            self,
            "result_digest",
            canonical_digest(
                {
                    "schema": "noetrium.research-portfolio-preflight.v1",
                    "portfolio_id": self.portfolio_id,
                    "portfolio_digest": self.portfolio_digest,
                    "authority_manifest_digest": self.authority_manifest_digest,
                    "execution_id": self.execution_id,
                    "revision_digest": self.revision_digest,
                    "selected_node_ids": self.selected_node_ids,
                    "admission_digests": self.admission_digests,
                    "preflight_digest": self.preflight_digest,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ResearchPortfolioExecutionResult:
    portfolio_id: str
    portfolio_digest: str
    authority_manifest_digest: str
    execution_id: str
    revision: ResearchGraphRevision
    receipt: ResearchControlReceipt
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _require_sha256(
            self.portfolio_digest,
            "research portfolio execution portfolio_digest",
        )
        _require_sha256(
            self.authority_manifest_digest,
            "research portfolio execution authority_manifest_digest",
        )
        if type(self.revision) is not ResearchGraphRevision:
            raise TypeError("research portfolio execution revision must be typed")
        if type(self.receipt) is not ResearchControlReceipt:
            raise TypeError("research portfolio execution receipt must be typed")
        object.__setattr__(
            self,
            "result_digest",
            canonical_digest(
                {
                    "schema": "noetrium.research-portfolio-execution-result.v1",
                    "portfolio_id": self.portfolio_id,
                    "portfolio_digest": self.portfolio_digest,
                    "authority_manifest_digest": self.authority_manifest_digest,
                    "execution_id": self.execution_id,
                    "revision_digest": self.revision.revision_digest,
                    "receipt": {
                        "action": self.receipt.action.value,
                        "execution_id": self.receipt.target.execution_id,
                        "revision_digest": self.receipt.target.revision.revision_digest,
                        "node": (
                            None
                            if self.receipt.target.node is None
                            else {
                                "program_id": self.receipt.target.node.program_id,
                                "node_id": self.receipt.target.node.node_id,
                            }
                        ),
                        "state": self.receipt.state,
                        "control_revision_digest": (
                            self.receipt.control_revision_digest
                        ),
                        "payload": self.receipt.payload,
                    },
                }
            ),
        )


def _revision_message(
    authority_manifest_digest: str,
    *,
    message: str | None,
) -> str:
    if message is not None:
        if type(message) is not str:
            raise TypeError("research execution revision message must be text")
        return message
    return f"research execution authorities {authority_manifest_digest}"


def _prospective_revision(
    portfolio: ResearchPortfolio,
    authorities: ResearchExecutionAuthorities,
    *,
    parents: tuple[ResearchGraphRevision, ...],
    message: str | None,
) -> ResearchGraphRevision:
    if type(portfolio) is not ResearchPortfolio:
        raise TypeError("research execution requires ResearchPortfolio")
    if type(authorities) is not ResearchExecutionAuthorities:
        raise TypeError("research execution requires ResearchExecutionAuthorities")
    if type(parents) is not tuple or any(
        type(parent) is not ResearchGraphRevision for parent in parents
    ):
        raise TypeError("research execution parents must be ResearchGraphRevision tuple")
    if any(parent.portfolio_id != portfolio.portfolio_id for parent in parents):
        raise ValueError("research execution parents must belong to portfolio")
    return ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        tuple(parent.revision_digest for parent in parents),
        _revision_message(
            authorities.authority_manifest_digest,
            message=message,
        ),
    )


def preflight_research_portfolio(
    portfolio: ResearchPortfolio,
    *,
    state_root: Path,
    authorities: ResearchExecutionAuthorities,
    execution_id: str | None = None,
    parents: tuple[ResearchGraphRevision, ...] = (),
    message: str | None = None,
    execution_pool: ResearchExecutionPool | None = None,
) -> ResearchPortfolioPreflightResult:
    """Run whole-portfolio admission without committing a durable revision/cut."""

    if not isinstance(state_root, Path):
        raise TypeError("research portfolio preflight state_root must be pathlib.Path")
    prospective = _prospective_revision(
        portfolio,
        authorities,
        parents=parents,
        message=message,
    )
    resolved_execution_id = portfolio.portfolio_id if execution_id is None else execution_id
    target = ResearchExecutionTarget(resolved_execution_id, prospective)
    composition = compose_local_research_os(
        state_root,
        experiment_closures=authorities.experiment_closures,
        experiment_runtime_components=authorities.experiment_runtime_components,
        execution_pool=execution_pool,
        method_runtime_inventory=authorities.method_runtime_inventory,
        content_authorities=compose_research_execution_content(
            state_root / "content"
        ),
    )
    try:
        prepared = composition.prepare(target, portfolio)
        return ResearchPortfolioPreflightResult(
            portfolio.portfolio_id,
            portfolio.portfolio_digest,
            authorities.authority_manifest_digest,
            resolved_execution_id,
            prospective.revision_digest,
            prepared.selected_node_ids,
            tuple(row.admission_digest for row in prepared.admissions),
            prepared.preflight_digest,
        )
    finally:
        composition.close()


def execute_research_portfolio(
    portfolio: ResearchPortfolio,
    *,
    state_root: Path,
    authorities: ResearchExecutionAuthorities,
    execution_id: str | None = None,
    parents: tuple[ResearchGraphRevision, ...] = (),
    message: str | None = None,
    execution_pool: ResearchExecutionPool | None = None,
) -> ResearchPortfolioExecutionResult:
    """Preflight, commit and RUN any ResearchPortfolio through one canonical path."""

    if not isinstance(state_root, Path):
        raise TypeError("research portfolio execution state_root must be pathlib.Path")
    prospective = _prospective_revision(
        portfolio,
        authorities,
        parents=parents,
        message=message,
    )
    resolved_execution_id = portfolio.portfolio_id if execution_id is None else execution_id
    target = ResearchExecutionTarget(resolved_execution_id, prospective)
    composition = compose_local_research_os(
        state_root,
        experiment_closures=authorities.experiment_closures,
        experiment_runtime_components=authorities.experiment_runtime_components,
        execution_pool=execution_pool,
        method_runtime_inventory=authorities.method_runtime_inventory,
        content_authorities=compose_research_execution_content(
            state_root / "content"
        ),
    )
    try:
        prepared = composition.prepare(target, portfolio)
        if prepared.target != target:
            raise RuntimeError("research portfolio preflight target identity drifted")
        revision = composition.research_os.commit(
            portfolio,
            parents=parents,
            message=prospective.message,
        )
        if revision != prospective:
            raise RuntimeError(
                "research portfolio revision drifted from preflighted identity"
            )
        receipt = composition.research_os.run(
            ResearchExecutionTarget(resolved_execution_id, revision)
        )
        return ResearchPortfolioExecutionResult(
            portfolio.portfolio_id,
            portfolio.portfolio_digest,
            authorities.authority_manifest_digest,
            resolved_execution_id,
            revision,
            receipt,
        )
    finally:
        composition.close()


__all__ = [
    "ResearchExecutionAuthorities",
    "ResearchExecutionAuthorityMaterializerPort",
    "ResearchExecutionContext",
    "ResearchPortfolioExecutionResult",
    "ResearchPortfolioPreflightResult",
    "execute_research_portfolio",
    "load_research_execution_authority_materializer",
    "open_local_research_execution_context",
    "preflight_research_portfolio",
]
