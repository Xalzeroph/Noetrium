from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import endpoint_unit, relation_unit, structure_unit

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, NoetriumUnit, NoetriumUnit


class RuntimeLaunchManifestPort(Protocol):
    """Read-only runtime view of an experiment-owned launch manifest.

    This is a behavioural port, not a second persisted manifest. The concrete
    record remains owned by `experimentation/run/manifest`.
    """

    release_digest: str
    prompt_generation_digest: str
    prompt_promotion_digest: str
    role_model_manifest_digest: str
    qualified_deployment_digests: tuple[str, ...]
    target_host_identity_digest: str
    participant_implementation_inventory_digest: str
    participant_runtime_inventory_digest: str
    participant_binding_manifest_digest: str
    experiment_spec_digest: str
    command_argv: tuple[str, ...]
    launcher_binary_sha256: str
    command_environment_digest: str
    config_digests: tuple[tuple[str, str], ...]
    seed_identity: str

    def digest(self) -> str: ...



class RuntimeAction(StrEnum):
    VERIFY_RELEASE = "verify_release"
    VERIFY_PROMPT_PROMOTION = "verify_prompt_promotion"
    VERIFY_HOST_INVENTORY = "verify_host_inventory"
    VERIFY_DEPLOYMENTS = "verify_deployments"
    RECONCILE_SERVICES = "reconcile_services"
    START_EXACT_SERVICES = "start_exact_services"
    VERIFY_SERVICES_READY = "verify_services_ready"
    VERIFY_RUNTIME_QUALIFICATION = "verify_runtime_qualification"
    VERIFY_PARTICIPANT_IMPLEMENTATIONS = "verify_participant_implementations"
    VERIFY_PARTICIPANT_RUNTIMES = "verify_participant_runtimes"
    VERIFY_PARTICIPANT_BINDINGS = "verify_participant_bindings"
    RECONCILE_RUN = "reconcile_run"
    START_EXACT_RUN = "start_exact_run"
    FINAL_STATUS = "final_status"


@dataclass(frozen=True, slots=True)
class RuntimeStep:
    action: RuntimeAction
    mutating: bool
    reconcile_anchor: RuntimeAction | None = None
    failure_reconcile_anchor: RuntimeAction | None = None


RUNTIME_PLAN_TRAIT = "runtime.launch-plan"
RUNTIME_STEP_TRAIT = "runtime.launch-step"

def runtime_plan(steps: tuple[RuntimeStep, ...]) -> NoetriumUnit:
    if type(steps) is not tuple or not steps: raise ValueError("runtime plan requires steps")
    members=tuple(structure_unit(f"step:{i}", traits=(RUNTIME_STEP_TRAIT,), parameters={"action":x.action.value,"mutating":x.mutating,"reconcile_anchor":None if x.reconcile_anchor is None else x.reconcile_anchor.value,"failure_reconcile_anchor":None if x.failure_reconcile_anchor is None else x.failure_reconcile_anchor.value}) for i,x in enumerate(steps))
    rel=tuple(relation_unit((endpoint_unit(members[i].unit_id,None),),(endpoint_unit(members[i+1].unit_id,None),),"runtime.sequence") for i in range(len(members)-1))
    return structure_unit("runtime:exact", traits=(RUNTIME_PLAN_TRAIT,), members=members, relations=rel)

def runtime_plan_steps(plan: NoetriumUnit) -> tuple[RuntimeStep, ...]:
    if type(plan) is not NoetriumUnit or not plan.has_trait(RUNTIME_PLAN_TRAIT): raise TypeError("runtime plan must be NoetriumUnit")
    rows=sorted(plan.members,key=lambda x:int(x.unit_id.split(":",1)[1])); out=[]
    for row in rows:
        p=row.parameters; ra=p.get("reconcile_anchor"); fa=p.get("failure_reconcile_anchor")
        out.append(RuntimeStep(RuntimeAction(str(p["action"])),bool(p["mutating"]),None if ra is None else RuntimeAction(str(ra)),None if fa is None else RuntimeAction(str(fa))))
    return tuple(out)

def exact_runtime_plan() -> NoetriumUnit:
    service_recovery = RuntimeAction.RECONCILE_SERVICES
    return runtime_plan((
        RuntimeStep(RuntimeAction.VERIFY_RELEASE, False),
        RuntimeStep(RuntimeAction.VERIFY_PROMPT_PROMOTION, False),
        RuntimeStep(RuntimeAction.VERIFY_HOST_INVENTORY, False),
        RuntimeStep(RuntimeAction.VERIFY_DEPLOYMENTS, False),
        RuntimeStep(RuntimeAction.RECONCILE_SERVICES, False),
        RuntimeStep(RuntimeAction.START_EXACT_SERVICES, True, RuntimeAction.RECONCILE_SERVICES),
        RuntimeStep(RuntimeAction.VERIFY_SERVICES_READY, False, failure_reconcile_anchor=service_recovery),
        RuntimeStep(RuntimeAction.VERIFY_RUNTIME_QUALIFICATION, False, failure_reconcile_anchor=service_recovery),
        RuntimeStep(RuntimeAction.VERIFY_PARTICIPANT_IMPLEMENTATIONS, False),
        RuntimeStep(RuntimeAction.VERIFY_PARTICIPANT_RUNTIMES, False),
        RuntimeStep(RuntimeAction.VERIFY_PARTICIPANT_BINDINGS, False),
        RuntimeStep(RuntimeAction.RECONCILE_RUN, False),
        RuntimeStep(RuntimeAction.START_EXACT_RUN, True, RuntimeAction.RECONCILE_RUN),
        RuntimeStep(RuntimeAction.FINAL_STATUS, False, failure_reconcile_anchor=service_recovery),
    ))
