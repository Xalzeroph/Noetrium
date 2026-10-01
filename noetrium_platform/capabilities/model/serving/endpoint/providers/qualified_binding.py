from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
import re
import time

from noetrium_platform.capabilities.model.serving.api.qualified_deployment import QualifiedDeploymentManifest, RoleModelManifest
from noetrium_platform.capabilities.model.serving.api.runtime_canary import RuntimeCanaryEvidence
from noetrium_platform.capabilities.model.serving.api.runtime_qualification_ports import RuntimeQualificationEvidenceStorePort
from noetrium_platform.substrate.api import ServiceHeartbeat

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from ..api import (
    ModelEndpointRoute,
    QualifiedModelEndpointBinding,
    QualifiedModelEndpointBindingPort,
    ModelEndpointReplicaSet,
)


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class QualifiedModelDeploymentClosure:
    """Already-persisted deployment facts needed by one endpoint consumer.

    This is a read projection over the model/serving authorities.  It does not
    create a deployment registry and it does not infer an endpoint from a
    readiness URL or operator environment variables.
    """

    role_manifest: RoleModelManifest
    deployments: tuple[QualifiedDeploymentManifest, ...]
    routes: tuple[ModelEndpointRoute, ...]
    runtime_manifest_digest: str
    runtime_qualifications: RuntimeQualificationEvidenceStorePort
    runtime_qualification_receipt_digests: tuple[tuple[str, str], ...]
    runtime_canary_evidence: tuple[RuntimeCanaryEvidence, ...]


class PersistedQualifiedModelEndpointBinding(QualifiedModelEndpointBindingPort):
    """Load one endpoint binding only after all qualification identities agree."""

    def __init__(
        self,
        closure: QualifiedModelDeploymentClosure,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not closure.runtime_manifest_digest.strip():
            raise ValueError("qualified deployment closure requires runtime manifest identity")
        self._roles = closure.role_manifest
        self._deployments = {item.deployment_id: item for item in closure.deployments}
        if len(self._deployments) != len(closure.deployments):
            raise ValueError("qualified deployment closure contains duplicate deployments")
        self._routes = {item.deployment_id: item for item in closure.routes}
        if len(self._routes) != len(closure.routes):
            raise ValueError("qualified deployment closure contains duplicate routes")
        self._runtime_manifest_digest = closure.runtime_manifest_digest
        self._runtime_qualifications = closure.runtime_qualifications
        receipt_digests = dict(closure.runtime_qualification_receipt_digests)
        if len(receipt_digests) != len(closure.runtime_qualification_receipt_digests):
            raise ValueError("qualified deployment closure contains duplicate runtime receipt identities")
        if set(receipt_digests) != set(self._deployments):
            raise ValueError("qualified deployment closure runtime receipt identities do not align")
        for digest in receipt_digests.values():
            if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
                raise ValueError("qualified deployment closure runtime receipt digest is invalid")
        self._runtime_receipt_digests = receipt_digests
        canaries_by_binding: dict[
            tuple[str, str, str, str, str], list[RuntimeCanaryEvidence]
        ] = {}
        for evidence in closure.runtime_canary_evidence:
            if evidence.passed:
                key=(
                    evidence.deployment_id,
                    evidence.role,
                    evidence.capability_id,
                    evidence.input_schema_id,
                    evidence.output_schema_id,
                )
                canaries_by_binding.setdefault(key, []).append(evidence)
        self._canaries_by_binding = {
            key: tuple(values) for key, values in canaries_by_binding.items()
        }
        self._clock = clock

    def _binding_for_deployment(
        self,
        deployment_id: str,
        *,
        role: str,
        capability_id: str,
        input_schema_id: str,
        output_schema_id: str,
        prompt_generation: str | None,
        now: float,
    ) -> QualifiedModelEndpointBinding:
        deployment = self._deployments.get(deployment_id)
        if deployment is None:
            raise ValueError(f"qualified deployment is missing: {deployment_id}")
        route = self._routes.get(deployment_id)
        if route is None:
            raise ValueError(f"qualified deployment has no endpoint route: {deployment_id}")
        deployment_generation = deployment.digest()
        if route.deployment_generation != deployment_generation:
            raise ValueError(f"qualified endpoint route generation drift: {deployment_id}")

        receipt = self._runtime_qualifications.load(
            self._runtime_manifest_digest,
            deployment_id,
        )
        if receipt.digest() != self._runtime_receipt_digests[deployment_id]:
            raise ValueError("runtime qualification receipt digest drift")
        certificate_digest = deployment.certificate.digest()
        stack_digest = deployment.stack.digest()
        if receipt.deployment_id != deployment_id:
            raise ValueError("runtime qualification receipt deployment drift")
        if receipt.stack_digest != stack_digest:
            raise ValueError("runtime qualification receipt stack drift")
        if receipt.qualification_certificate_digest != certificate_digest:
            raise ValueError("runtime qualification receipt certificate drift")
        heartbeat = ServiceHeartbeat(
            receipt.deployment_id, receipt.stack_digest, receipt.process_pid,
            receipt.process_start_marker, receipt.argv_digest, True,
            receipt.heartbeat_qualification_digest, receipt.heartbeat_timestamp,
        )
        if f"heartbeat:sha256:{canonical_digest(heartbeat)}" not in receipt.evidence_refs:
            raise ValueError("runtime qualification receipt heartbeat evidence drift")
        if role not in receipt.qualified_roles:
            raise ValueError(f"runtime qualification receipt does not qualify role: {role}")
        if receipt.created_at > now:
            raise ValueError("runtime qualification receipt is from the future")
        canary_key=(deployment_id,role,capability_id,input_schema_id,output_schema_id)
        canaries = self._canaries_by_binding.get(canary_key, ())
        if not canaries:
            raise ValueError(
                "runtime canary evidence does not qualify model capability: "
                f"{(role, capability_id, input_schema_id, output_schema_id)}"
            )
        route_digest = canonical_digest(route)
        for evidence in canaries:
            if evidence.deployment_generation != deployment_generation:
                raise ValueError("runtime canary deployment generation drift")
            if evidence.route_digest != route_digest:
                raise ValueError("runtime canary route digest drift")
            if (evidence.process_pid, evidence.process_start_marker, evidence.argv_digest) != (
                receipt.process_pid, receipt.process_start_marker, receipt.argv_digest
            ):
                raise ValueError("runtime canary process generation drift")
            if not receipt.heartbeat_timestamp <= evidence.observed_at <= receipt.valid_until:
                raise ValueError("runtime canary observation outside qualification validity")
            if f"canary:sha256:{evidence.evidence_digest}" not in receipt.evidence_refs:
                raise ValueError("runtime qualification receipt does not bind runtime canary evidence")

        return QualifiedModelEndpointBinding(
            role=role,
            capability_id=capability_id,
            input_schema_id=input_schema_id,
            output_schema_id=output_schema_id,
            deployment_id=deployment_id,
            deployment_generation=deployment_generation,
            base_url=route.base_url,
            model=deployment.stack.identity,
            model_stack_digest=stack_digest,
            qualification_certificate_digest=certificate_digest,
            runtime_qualification_digest=receipt.digest(),
            host_identity_digest=deployment.host_identity_digest,
            prompt_generation=prompt_generation,
            max_admitted_concurrency=deployment.certificate.resource_envelope.max_qualified_concurrency,
            preferred_admitted_concurrency=(
                deployment.certificate.resource_envelope
                .preferred_operating_concurrency
            ),
            runtime_canary_evidence_digests=tuple(item.evidence_digest for item in canaries),
            tokenizer_sha256=deployment.stack.artifacts.tokenizer_sha256,
            chat_template_sha256=deployment.stack.artifacts.chat_template_sha256,
            verified_capabilities=tuple(sorted({
                capability
                for item in canaries
                for capability in item.verified_capabilities
            })),
            completion_path=route.completion_path,
            timeout_s=route.timeout_s,
        )

    def binding_for(
        self,
        *,
        role: str,
        capability_id: str,
        input_schema_id: str,
        output_schema_id: str,
        prompt_generation: str | None = None,
    ) -> QualifiedModelEndpointBinding:
        """Revalidate the canonical frozen deployment assigned to one role."""

        for name,value in (
            ("role",role),
            ("capability_id",capability_id),
            ("input_schema_id",input_schema_id),
            ("output_schema_id",output_schema_id),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"qualified model binding {name} is required")
        if prompt_generation is not None and (
            type(prompt_generation) is not str
            or not prompt_generation.strip()
        ):
            raise ValueError(
                "qualified model binding prompt generation must be non-empty text or None"
            )
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("runtime qualification binding clock must be finite")
        deployment_id = self._roles.deployment_for(
            role,capability_id,input_schema_id,output_schema_id
        )
        if deployment_id not in self._deployments:
            raise ValueError(f"qualified role assignment has no deployment: {deployment_id}")
        return self._binding_for_deployment(
            deployment_id,
            role=role,
            capability_id=capability_id,
            input_schema_id=input_schema_id,
            output_schema_id=output_schema_id,
            prompt_generation=prompt_generation,
            now=now,
        )

    def replica_set_for(
        self,
        *,
        role: str,
        capability_id: str,
        input_schema_id: str,
        output_schema_id: str,
        prompt_generation: str | None = None,
    ) -> ModelEndpointReplicaSet:
        """Discover every currently valid replica of the canonical role binding.

        The role manifest still freezes the scientific model choice to exactly one
        canonical deployment. Additional deployments are eligible only when they
        prove the exact same immutable model and stack and independently carry a
        generation-bound qualification receipt plus passed canary evidence for the role.
        Identity-drifted or unqualified operational replicas are omitted; the canonical
        role assignment itself must remain valid or resolution fails closed.
        """

        canonical = self.binding_for(
            role=role,
            capability_id=capability_id,
            input_schema_id=input_schema_id,
            output_schema_id=output_schema_id,
            prompt_generation=prompt_generation,
        )
        now = float(self._clock())
        values = [canonical]
        for deployment_id, deployment in sorted(self._deployments.items()):
            if deployment_id == canonical.deployment_id:
                continue
            if deployment.stack.identity != canonical.model:
                continue
            if deployment.stack.digest() != canonical.model_stack_digest:
                continue
            if deployment_id not in self._routes:
                continue
            if (
                deployment_id,
                role,
                capability_id,
                input_schema_id,
                output_schema_id,
            ) not in self._canaries_by_binding:
                continue
            try:
                binding = self._binding_for_deployment(
                    deployment_id,
                    role=role,
                    capability_id=capability_id,
                    input_schema_id=input_schema_id,
                    output_schema_id=output_schema_id,
                    prompt_generation=prompt_generation,
                    now=now,
                )
            except (KeyError, ValueError):
                continue
            if binding.verified_capabilities != canonical.verified_capabilities:
                continue
            values.append(binding)
        return ModelEndpointReplicaSet(tuple(values))


__all__ = [
    "PersistedQualifiedModelEndpointBinding",
    "QualifiedModelDeploymentClosure",
]
