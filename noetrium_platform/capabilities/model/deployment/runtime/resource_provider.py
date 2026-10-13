from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest
from noetrium_platform.substrate.api import (
    NoetriumUnit,
    is_physical_identity,
    is_realization_ticket,
    observation_field,
    physical_field,
    physical_identity,
    realization_ticket,
    resource_observation,
    ticket_field,
)

from ..api import (
    ModelAppliedServiceAbsent,
    ModelDeploymentCatalogPort,
    ModelDeploymentRuntimePort,
    ModelRuntimeState,
)
from .codec import decode_deployment, deployment_to_data


def model_resource_deployment_id(
    resource_key: str,
    generation: int,
) -> str:
    if type(resource_key) is not str or not resource_key.strip():
        raise ValueError("model resource key must be non-empty text")
    if type(generation) is not int or generation < 1:
        raise ValueError("model resource generation must be positive")
    return (
        "model-resource-"
        + canonical_digest(
            {
                "resource_key": resource_key,
                "generation": generation,
            }
        )[:40]
    )


class ModelServicePhysicalProvider:
    """Ticket-addressable physical ISA for one model service generation."""

    provider_kind = "model-service"

    def __init__(
        self,
        *,
        catalog: ModelDeploymentCatalogPort,
        runtime: ModelDeploymentRuntimePort,
    ) -> None:
        self._catalog = catalog
        self._runtime = runtime

    @staticmethod
    def _deployment_data(
        spec: Mapping[str, JsonValue],
    ) -> dict[str, object]:
        raw = spec.get("deployment")
        if not isinstance(raw, dict):
            raise ValueError(
                "model-service realization requires deployment data"
            )
        return {str(key): value for key, value in raw.items()}

    @staticmethod
    def _identity(
        ticket: NoetriumUnit,
        *,
        deployment_id: str,
        applied_runtime_digest: str | None,
        pid: int | None,
    ) -> NoetriumUnit:
        return physical_identity(
            ModelServicePhysicalProvider.provider_kind,
            deployment_id,
            {
                "resource_key": ticket_field(ticket, "resource_key"),
                "generation": ticket_field(ticket, "generation"),
                "ticket_id": ticket_field(ticket, "ticket_id"),
                "spec_digest": ticket_field(ticket, "spec_digest"),
                "applied_runtime_digest": applied_runtime_digest,
                "pid": pid,
            },
        )

    def realize(
        self,
        spec: Mapping[str, JsonValue],
        ticket: NoetriumUnit,
    ) -> NoetriumUnit:
        deployment = decode_deployment(self._deployment_data(spec))
        expected_id = model_resource_deployment_id(
            ticket_field(ticket, "resource_key"),
            ticket_field(ticket, "generation"),
        )
        if deployment.deployment_id != expected_id:
            raise RuntimeError(
                "model deployment id crossed Authority resource generation"
            )
        persisted = self._catalog.put_deployment(deployment)
        if canonical_digest(persisted) != canonical_digest(deployment):
            raise RuntimeError(
                "model deployment catalog changed realization spec"
            )
        generation = self._runtime.generation(expected_id)
        if generation.desired_deployment_digest != canonical_digest(deployment):
            raise RuntimeError(
                "model desired generation does not match ticket realization"
            )
        status = self._runtime.start(generation)
        if status.runtime_state is not ModelRuntimeState.RUNNING:
            raise RuntimeError(
                "model physical realization did not become running: "
                f"{expected_id}:{status.runtime_state.value}:{status.detail}"
            )
        final = self._runtime.generation(expected_id)
        if final.applied_runtime_digest is None:
            raise RuntimeError(
                "running model realization has no applied runtime digest"
            )
        return self._identity(
            ticket,
            deployment_id=expected_id,
            applied_runtime_digest=final.applied_runtime_digest,
            pid=status.pid,
        )

    def observe(
        self,
        reference: NoetriumUnit,
    ) -> NoetriumUnit:
        if is_realization_ticket(reference):
            ticket = reference
            deployment_id = model_resource_deployment_id(
                ticket_field(ticket, "resource_key"),
                ticket_field(ticket, "generation"),
            )
        elif is_physical_identity(reference):
            if physical_field(reference, "provider_kind") != self.provider_kind:
                raise ValueError(
                    "foreign physical identity passed to model provider"
                )
            attrs = dict(physical_field(reference, "attributes") or {})
            try:
                resource_key = str(attrs["resource_key"])
                generation = int(attrs["generation"])
                ticket_id = str(attrs["ticket_id"])
                spec_digest = str(attrs["spec_digest"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    "model physical identity lacks Authority metadata"
                ) from exc
            ticket = realization_ticket(
                ticket_id=ticket_id,
                effect_id="observation:" + ticket_id,
                realization_key="observation:" + ticket_id,
                resource_key=resource_key,
                provider_kind=self.provider_kind,
                generation=generation,
                spec_digest=spec_digest,
                holder_key="observation",
            )
            deployment_id = physical_field(reference, "physical_id")
            expected_id = model_resource_deployment_id(
                resource_key,
                generation,
            )
            if deployment_id != expected_id:
                raise RuntimeError(
                    "model physical identity crossed Authority generation"
                )
        else:
            raise TypeError(
                "model observe requires ticket or physical-identity Unit"
            )

        try:
            generation = self._runtime.generation(deployment_id)
            if generation.applied_runtime_digest is None:
                try:
                    generation = self._runtime.recover_applied(generation)
                except ModelAppliedServiceAbsent:
                    return resource_observation(
                        ticket_field(ticket, "resource_key"),
                        ticket_field(ticket, "generation"),
                        ticket_field(ticket, "ticket_id"),
                        ticket_field(ticket, "spec_digest"),
                        False,
                        False,
                        None,
                        evidence={
                            "deployment_id": deployment_id,
                            "runtime_state": ModelRuntimeState.MISSING.value,
                            "applied_runtime_digest": None,
                            "pid": None,
                        },
                    )
            status = self._runtime.status(deployment_id)
        except (KeyError, FileNotFoundError):
            return resource_observation(
                ticket_field(ticket, "resource_key"),
                ticket_field(ticket, "generation"),
                ticket_field(ticket, "ticket_id"),
                ticket_field(ticket, "spec_digest"),
                False,
                False,
                None,
            )

        exists = status.runtime_state not in {
            ModelRuntimeState.STOPPED,
            ModelRuntimeState.MISSING,
        }
        ready = status.runtime_state is ModelRuntimeState.RUNNING
        identity = (
            self._identity(
                ticket,
                deployment_id=deployment_id,
                applied_runtime_digest=generation.applied_runtime_digest,
                pid=status.pid,
            )
            if exists
            else None
        )
        return resource_observation(
            resource_key=ticket_field(ticket, "resource_key"),
            generation=ticket_field(ticket, "generation"),
            ticket_id=ticket_field(ticket, "ticket_id"),
            spec_digest=ticket_field(ticket, "spec_digest"),
            exists=exists,
            ready=ready,
            physical=identity,
            evidence={
                "deployment_id": deployment_id,
                "runtime_state": status.runtime_state.value,
                "applied_runtime_digest": generation.applied_runtime_digest,
                "pid": status.pid,
            },
        )

    def retire(
        self,
        reference: NoetriumUnit,
        ticket: NoetriumUnit,
    ) -> NoetriumUnit:
        expected_id = model_resource_deployment_id(
            ticket_field(ticket, "resource_key"),
            ticket_field(ticket, "generation"),
        )
        if is_physical_identity(reference):
            if (
                physical_field(reference, "provider_kind") != self.provider_kind
                or physical_field(reference, "physical_id") != expected_id
            ):
                raise RuntimeError(
                    "model retire reference crossed Authority ticket"
                )
        try:
            generation = self._runtime.generation(expected_id)
        except (KeyError, FileNotFoundError):
            return self.observe(ticket)
        self._runtime.remove_deployment(generation)
        final = self.observe(ticket)
        if observation_field(final, "exists"):
            raise RuntimeError(
                "model physical realization survived retirement"
            )
        return final


def model_realization_parameters(
    deployment,
) -> Mapping[str, JsonValue]:
    data = deployment_to_data(deployment)
    return {"deployment": data}


__all__ = [
    "ModelServicePhysicalProvider",
    "model_realization_parameters",
    "model_resource_deployment_id",
]
