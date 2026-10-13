from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import structure_unit
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
"""Canonical recursive-NoetriumUnit research execution composition.

Every authoring/discovery surface produces one immutable research.portfolio Unit.
Execution is cardinality-agnostic: one program and one hundred programs use the
same authority materialization, preflight, control, pool and shutdown path.
"""

import importlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.infrastructure.lifecycle.runtime import (
    ResourceLifetimeController,
    ResourceLifetimeLease,
    ResourceLifetimeRegistration,
)
from noetrium_platform.infrastructure.resources.directory.runtime import (
    standard_local_directory_layout,
)
from noetrium_platform.product.research_unit import require_research_root
from noetrium_platform.product.research_control import (
    ResearchControlReceipt,
    ResearchExecutionTarget,
    ResearchGraphRevision,
)
from noetrium_platform.research.execution.policy.api import (
    ExecutionBudgetAuthorityPort,
)
from noetrium_platform.research.execution.policy.runtime import (
    SQLiteExecutionBudgetAuthority,
)
from noetrium_platform.research.execution.workflow.api import (
    OperationDispatchPort,
    MethodRuntimePortInventory,
)

from .managed_research_runtime import (
    ManagedResearchRuntime,
    build_local_managed_research_runtime,
)
from .research_authority_inputs import (
    authority_input_value,
    normalize_authority_inputs,
)
from .research_binding_authority import ResearchBindingAuthorityPort
from .research_symbol_authority import (
    ResearchSymbolBindingAuthorityPort,
)
from .research_execution_content import (
    ResearchExecutionContentAuthorities,
    compose_research_execution_content,
)
from .research_execution_pool import ResearchExecutionPool
from .research_experiment import (
    ResearchExperimentCompilationPort,
    ResearchExperimentRuntimeBindingPort,
)
from .research_runtime_local import compose_local_research_runtime
from .research_study_closure import ResearchExperimentCompilationProvider


def compose_research_portfolio_roots(
    portfolios: tuple[NoetriumUnit, ...],
    *,
    root_id: str | None = None,
) -> NoetriumUnit:
    """Compose one recursive execution root from one or many portfolios.

    Cardinality never changes execution semantics.  Existing portfolio roots are
    inserted directly as child NoetriumUnits with structural sharing; no
    wrapper node type, adapter, scheduler or compatibility path is introduced.
    """

    if (
        type(portfolios) is not tuple
        or not portfolios
        or any(type(row) is not NoetriumUnit for row in portfolios)
    ):
        raise TypeError(
            "research portfolio root composition requires non-empty "
            "NoetriumUnit tuple"
        )
    for row in portfolios:
        require_research_root(row)
    ids = tuple(row.unit_id for row in portfolios)
    if len(ids) != len(set(ids)):
        raise ValueError(
            "research portfolio root identities must be unique"
        )
    digest = canonical_digest(
        {
            "schema": "noetrium.research-root-set.v1",
            "portfolios": tuple(
                sorted(
                    (row.unit_id, row.unit_digest)
                    for row in portfolios
                )
            ),
        }
    )
    resolved_root_id = (
        f"research-root-{digest[:24]}"
        if root_id is None
        else root_id
    )
    return structure_unit(
        resolved_root_id,
        traits=("research.portfolio",),
        parameters={
            "portfolio_count": len(portfolios),
            "root_set_digest": digest,
        },
        members=portfolios,
    )


def _require_sha256(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class ResearchExecutionAuthorities:
    """Execution-scoped borrower/owner authority bundle for one frozen portfolio."""

    authority_manifest_digest: str
    lifetime_controller: ResourceLifetimeController
    experiment_compilation: ResearchExperimentCompilationPort | None = None
    experiment_runtime_binding: ResearchExperimentRuntimeBindingPort | None = None
    method_runtime_inventory: MethodRuntimePortInventory | None = None
    symbol_bindings: ResearchSymbolBindingAuthorityPort | None = None
    lifetime_resources: tuple[ResourceLifetimeRegistration, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _require_sha256(
            self.authority_manifest_digest,
            "research execution authority_manifest_digest",
        )
        if not isinstance(self.lifetime_controller, ResourceLifetimeController):
            raise TypeError(
                "research execution authorities require ResourceLifetimeController"
            )
        if (self.experiment_compilation is None) != (
            self.experiment_runtime_binding is None
        ):
            raise ValueError(
                "research execution Experimentation authority requires both "
                "closure resolver and runtime binding authority"
            )
        if self.experiment_compilation is not None and not isinstance(
            self.experiment_compilation,
            ResearchExperimentCompilationPort,
        ):
            raise TypeError(
                "research execution experiment_compilation must satisfy "
                "ResearchExperimentCompilationPort"
            )
        if (
            self.experiment_runtime_binding is not None
            and not isinstance(
                self.experiment_runtime_binding,
                ResearchExperimentRuntimeBindingPort,
            )
        ):
            raise TypeError(
                "research execution experiment_runtime_binding must satisfy "
                "ResearchExperimentRuntimeBindingPort"
            )
        if self.symbol_bindings is not None and not isinstance(
            self.symbol_bindings,
            ResearchSymbolBindingAuthorityPort,
        ):
            raise TypeError(
                "research execution symbol_bindings must satisfy typed port"
            )
        if self.method_runtime_inventory is not None and not isinstance(
            self.method_runtime_inventory,
            MethodRuntimePortInventory,
        ):
            raise TypeError(
                "research execution method_runtime_inventory must be "
                "MethodRuntimePortInventory"
            )
        if type(self.lifetime_resources) is not tuple or any(
            type(resource) is not ResourceLifetimeRegistration
            for resource in self.lifetime_resources
        ):
            raise TypeError(
                "research execution lifetime_resources must be typed owner tokens"
            )
        if any(
            resource.owner_generation_id
            != self.lifetime_controller.owner_generation_id
            for resource in self.lifetime_resources
        ):
            raise ValueError(
                "research execution lifetime resource owner generation drift"
            )

    def acquire_execution_lease(self, holder_key: str) -> ResourceLifetimeLease:
        return self.lifetime_controller.acquire(holder_key)

    def retire(self) -> tuple[str, ...]:
        return self.lifetime_controller.retire_all()

    @classmethod
    def from_study_bindings(
        cls,
        authority_manifest_digest: str,
        *,
        lifetime_controller: ResourceLifetimeController,
        research_bindings: ResearchBindingAuthorityPort,
        experiment_runtime_binding: ResearchExperimentRuntimeBindingPort,
        method_runtime_inventory: MethodRuntimePortInventory | None = None,
        symbol_bindings: ResearchSymbolBindingAuthorityPort | None = None,
        pre_materialized_studies: Mapping[str, NoetriumUnit] | None = None,
        precompiled_experiments: Mapping[
            str, tuple[NoetriumUnit, object, NoetriumUnit, NoetriumUnit]
        ] | None = None,
        lifetime_resources: tuple[ResourceLifetimeRegistration, ...] = (),
    ) -> "ResearchExecutionAuthorities":
        if not isinstance(research_bindings, ResearchBindingAuthorityPort):
            raise TypeError(
                "research execution research_bindings must satisfy "
                "ResearchBindingAuthorityPort"
            )
        return cls(
            authority_manifest_digest,
            lifetime_controller,
            ResearchExperimentCompilationProvider(
                research_bindings,
                symbol_bindings=symbol_bindings,
                pre_materialized_studies=pre_materialized_studies,
                precompiled_experiments=precompiled_experiments,
            ),
            experiment_runtime_binding,
            method_runtime_inventory,
            symbol_bindings,
            lifetime_resources,
        )


@dataclass(frozen=True, slots=True)
class ResearchExecutionContext:
    """Shared physical/runtime authority context for any research-root cardinality."""

    state_root: Path
    runtime: ManagedResearchRuntime
    content: ResearchExecutionContentAuthorities | None = None
    authority_inputs: tuple[tuple[str, str], ...] = ()
    execution_budget: ExecutionBudgetAuthorityPort | None = None
    execution_tenant_id: str | None = None
    causal_context: ExecutionContext | None = None
    causal_event_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.state_root, Path):
            raise TypeError("research execution context state_root must be pathlib.Path")
        if not isinstance(self.runtime, ManagedResearchRuntime):
            raise TypeError(
                "research execution context runtime must be ManagedResearchRuntime"
            )
        if self.causal_context is not None and not isinstance(
            self.causal_context, ExecutionContext
        ):
            raise TypeError(
                "research execution causal_context must be ExecutionContext or None"
            )
        if type(self.causal_event_refs) is not tuple:
            raise TypeError("research execution causal_event_refs must be tuple")
        for digest in self.causal_event_refs:
            require_sha256(digest, "research execution causal event ref")
        if len(self.causal_event_refs) != len(set(self.causal_event_refs)):
            raise ValueError("research execution causal event refs must be unique")
        if self.execution_tenant_id is not None:
            if (
                type(self.execution_tenant_id) is not str
                or not self.execution_tenant_id.strip()
            ):
                raise ValueError(
                    "research execution context tenant must be non-empty text or None"
                )
            object.__setattr__(
                self,
                "execution_tenant_id",
                self.execution_tenant_id.strip(),
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
        object.__setattr__(
            self,
            "authority_inputs",
            normalize_authority_inputs(
                self.authority_inputs,
                label="research execution authority_inputs",
            ),
        )
        if self.execution_budget is None:
            checkpoint_replay_proof = canonical_digest(
                {
                    "schema": "noetrium.machine-checkpoint-replay-proof.v1",
                    "journal": "DirectoryMachineJournal",
                    "durability": "crash_durable",
                }
            )
            exact_replay_proof = self.authority_input(
                "replay.exact_proof_digest"
            )
            # Cost admission requires a typed accounting authority. A digest-only
            # configuration is not sufficient proof and therefore cannot enable it.
            cost_accounting = None
            object.__setattr__(
                self,
                "execution_budget",
                SQLiteExecutionBudgetAuthority(
                    self.state_root / "execution-budget.sqlite3",
                    resource_policy_digest=(
                        self.runtime.execution_pool.resource_competition_policy_digest
                    ),
                    checkpoint_replay_proof_digest=checkpoint_replay_proof,
                    exact_replay_proof_digest=exact_replay_proof,
                    cost_accounting_digest=cost_accounting,
                ),
            )
        elif not isinstance(
            self.execution_budget,
            ExecutionBudgetAuthorityPort,
        ):
            raise TypeError(
                "research execution context execution_budget must satisfy "
                "ExecutionBudgetAuthorityPort"
            )

    def authority_input(self, key: str) -> str | None:
        return authority_input_value(
            self.authority_inputs,
            key,
            label="research execution authority input",
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
    """Materialize exact owner authorities for one frozen research.portfolio Unit."""

    def materialize(
        self,
        portfolio: NoetriumUnit,
    ) -> ResearchExecutionAuthorities: ...


def load_research_execution_authority_materializer(
    spec: str,
    context: ResearchExecutionContext,
) -> ResearchExecutionAuthorityMaterializerPort:
    """Load one public materializer factory for any research.portfolio Unit."""

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
    authority_inputs: tuple[tuple[str, str], ...] = (),
    terminal_retirement_on_success: bool = False,
) -> Iterator[ResearchExecutionContext]:
    """Open the one ManagedResearchRuntime used by a portfolio execution."""

    if not isinstance(state_root, Path):
        raise TypeError("research execution state_root must be pathlib.Path")
    resolved_root = state_root.expanduser().absolute()
    runtime = build_local_managed_research_runtime(
        standard_local_directory_layout(resolved_root / "platform-runtime"),
    )
    context = ResearchExecutionContext(
        resolved_root,
        runtime,
        authority_inputs=authority_inputs,
    )
    try:
        yield context
    except BaseException as primary:
        try:
            runtime.close()
        except BaseException as cleanup:
            raise BaseExceptionGroup(
                "research execution and runtime shutdown failed",
                [primary, cleanup],
            )
        raise
    else:
        if terminal_retirement_on_success:
            runtime.retire_runtime_fabric()
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
                        "graph": (
                            None
                            if self.receipt.target.graph is None
                            else self.receipt.target.graph.path
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
    portfolio: NoetriumUnit,
    authorities: ResearchExecutionAuthorities,
    *,
    parents: tuple[ResearchGraphRevision, ...],
    message: str | None,
) -> ResearchGraphRevision:
    require_research_root(portfolio)
    if type(authorities) is not ResearchExecutionAuthorities:
        raise TypeError("research execution requires ResearchExecutionAuthorities")
    if type(parents) is not tuple or any(
        type(parent) is not ResearchGraphRevision for parent in parents
    ):
        raise TypeError("research execution parents must be ResearchGraphRevision tuple")
    if any(parent.portfolio_id != portfolio.unit_id for parent in parents):
        raise ValueError("research execution parents must belong to portfolio")
    return ResearchGraphRevision(
        portfolio.unit_id,
        portfolio.unit_digest,
        tuple(parent.revision_digest for parent in parents),
        _revision_message(
            authorities.authority_manifest_digest,
            message=message,
        ),
    )


def preflight_research_portfolio(
    portfolio: NoetriumUnit,
    *,
    state_root: Path,
    authorities: ResearchExecutionAuthorities,
    execution_id: str | None = None,
    parents: tuple[ResearchGraphRevision, ...] = (),
    message: str | None = None,
    execution_pool: ResearchExecutionPool | None = None,
    operation_dispatcher: OperationDispatchPort | None = None,
    content_authorities: ResearchExecutionContentAuthorities | None = None,
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
    resolved_execution_id = portfolio.unit_id if execution_id is None else execution_id
    target = ResearchExecutionTarget(resolved_execution_id, prospective)
    composition = compose_local_research_runtime(
        state_root,
        experiment_compilation=authorities.experiment_compilation,
        experiment_runtime_binding=authorities.experiment_runtime_binding,
        symbol_bindings=authorities.symbol_bindings,
        execution_pool=execution_pool,
        method_runtime_inventory=authorities.method_runtime_inventory,
        operation_dispatcher=operation_dispatcher,
        content_authorities=(
            compose_research_execution_content(state_root / "content")
            if content_authorities is None
            else content_authorities
        ),
    )
    try:
        prepared = composition.prepare(target, portfolio)
        return ResearchPortfolioPreflightResult(
            portfolio.unit_id,
            portfolio.unit_digest,
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
    portfolio: NoetriumUnit,
    *,
    state_root: Path,
    authorities: ResearchExecutionAuthorities,
    execution_id: str | None = None,
    parents: tuple[ResearchGraphRevision, ...] = (),
    message: str | None = None,
    execution_pool: ResearchExecutionPool | None = None,
    operation_dispatcher: OperationDispatchPort | None = None,
    content_authorities: ResearchExecutionContentAuthorities | None = None,
) -> ResearchPortfolioExecutionResult:
    """Preflight, commit and RUN any research.portfolio Unit through one canonical path."""

    if not isinstance(state_root, Path):
        raise TypeError("research portfolio execution state_root must be pathlib.Path")
    if operation_dispatcher is None:
        raise RuntimeError(
            "research portfolio execution requires managed durable Operation authority"
        )
    prospective = _prospective_revision(
        portfolio,
        authorities,
        parents=parents,
        message=message,
    )
    resolved_execution_id = portfolio.unit_id if execution_id is None else execution_id
    target = ResearchExecutionTarget(resolved_execution_id, prospective)
    composition = compose_local_research_runtime(
        state_root,
        experiment_compilation=authorities.experiment_compilation,
        experiment_runtime_binding=authorities.experiment_runtime_binding,
        symbol_bindings=authorities.symbol_bindings,
        execution_pool=execution_pool,
        method_runtime_inventory=authorities.method_runtime_inventory,
        operation_dispatcher=operation_dispatcher,
        content_authorities=(
            compose_research_execution_content(state_root / "content")
            if content_authorities is None
            else content_authorities
        ),
    )
    try:
        prepared = composition.prepare(target, portfolio)
        if prepared.target != target:
            raise RuntimeError("research portfolio preflight target identity drifted")
        revision = composition.control.commit(
            portfolio,
            parents=parents,
            message=prospective.message,
        )
        if revision != prospective:
            raise RuntimeError(
                "research portfolio revision drifted from preflighted identity"
            )
        receipt = composition.control.run(
            ResearchExecutionTarget(resolved_execution_id, revision)
        )
        return ResearchPortfolioExecutionResult(
            portfolio.unit_id,
            portfolio.unit_digest,
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
    "compose_research_portfolio_roots",
    "execute_research_portfolio",
    "load_research_execution_authority_materializer",
    "open_local_research_execution_context",
    "preflight_research_portfolio",
]
