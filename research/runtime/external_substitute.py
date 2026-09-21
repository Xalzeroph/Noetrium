from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointRoute,
    OperationalModelEndpointReplica,
)
from noetrium_platform.foundation.kernel.kernel import (
    ImmutableModelIdentity,
    canonical_digest,
)


_SHA64 = re.compile(r"[0-9a-f]{64}\Z")


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA64.fullmatch(value) is None:
        raise ValueError(f"{field} must be lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class ExternalSubstituteModelDeployment:
    """Verified non-claim deployment receipt for research substitute runs."""

    model: ImmutableModelIdentity
    deployment_id: str
    deployment_generation: str
    endpoint_base_url: str
    identity_document_digest: str

    @property
    def model_identity_digest(self) -> str:
        return canonical_digest(self.model)

    def operational_replica(
        self,
        *,
        capacity: int,
        timeout_s: float = 180.0,
    ) -> OperationalModelEndpointReplica:
        return OperationalModelEndpointReplica(
            ModelEndpointRoute(
                self.deployment_id,
                self.deployment_generation,
                self.endpoint_base_url,
                timeout_s=timeout_s,
            ),
            capacity,
        )


def _model_identity(document: dict[str, object]) -> ImmutableModelIdentity:
    model = document.get("model")
    if not isinstance(model, dict):
        raise ValueError("external substitute identity has no model object")
    revision = _require_sha256(model.get("revision"), "model revision")
    tokenizer_revision = _require_sha256(
        model.get("tokenizer_revision"),
        "model tokenizer_revision",
    )
    return ImmutableModelIdentity(
        logical_name=str(model["logical_name"]),
        model_id=str(model["model_id"]),
        revision=revision,
        engine=str(model["engine"]),
        engine_version=str(model["engine_version"]),
        dtype=str(model["dtype"]),
        quantization=model.get("quantization"),
        context_length=int(model["context_length"]),
        tokenizer_revision=tokenizer_revision,
    )


def load_external_substitute_model_deployment(
    path: str | Path,
) -> ExternalSubstituteModelDeployment:
    source = Path(path)
    document = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError(f"{source}: expected JSON object")
    if document.get("schema") != "noetrium.external-model-identity.v2":
        raise ValueError("external substitute identity schema mismatch")
    if document.get("lane") != "platform-substitute":
        raise ValueError("external substitute identity must use platform-substitute lane")
    if document.get("matched_reproduction") is not False:
        raise ValueError("external substitute identity must reject matched reproduction")

    identity_document_digest = _require_sha256(
        document.get("identity_digest"),
        "external substitute identity document digest",
    )
    payload = dict(document)
    payload.pop("identity_digest", None)
    if canonical_digest(payload) != identity_document_digest:
        raise ValueError("external substitute identity document digest mismatch")

    deployment_id = document.get("deployment_id")
    if not isinstance(deployment_id, str) or not deployment_id.strip():
        raise ValueError("external substitute deployment_id is required")
    deployment_generation = _require_sha256(
        document.get("deployment_generation"),
        "external substitute deployment_generation",
    )
    observation = document.get("deployment_observation")
    if not isinstance(observation, dict):
        raise ValueError("external substitute deployment observation is required")
    endpoint = observation.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError("external substitute deployment endpoint is required")

    model = _model_identity(document)
    observed_model_manifest = observation.get("model_manifest_digest")
    if observed_model_manifest is not None:
        observed_model_manifest = _require_sha256(
            observed_model_manifest,
            "external substitute observed model manifest digest",
        )
        if observed_model_manifest != model.revision:
            raise ValueError("external substitute model manifest/revision drift")

    # Constructor validation also rejects malformed or non-HTTP endpoint routes.
    ModelEndpointRoute(deployment_id, deployment_generation, endpoint)
    return ExternalSubstituteModelDeployment(
        model=model,
        deployment_id=deployment_id,
        deployment_generation=deployment_generation,
        endpoint_base_url=endpoint,
        identity_document_digest=identity_document_digest,
    )


__all__ = [
    "ExternalSubstituteModelDeployment",
    "load_external_substitute_model_deployment",
]
