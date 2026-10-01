from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity


def _require_digest(value: str, field: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class QualifiedModelEndpointBinding:
    """Frozen endpoint identity imported from model/deployment qualification.

    Projects may consume this contract, but cannot construct scientific model
    identity from ad-hoc environment variables once the binding is required.
    """

    role: str
    capability_id: str
    input_schema_id: str
    output_schema_id: str
    deployment_id: str
    deployment_generation: str
    base_url: str
    model: ImmutableModelIdentity
    model_stack_digest: str
    qualification_certificate_digest: str
    runtime_qualification_digest: str
    host_identity_digest: str
    prompt_generation: str | None
    max_admitted_concurrency: int
    runtime_canary_evidence_digests: tuple[str, ...]
    tokenizer_sha256: str | None
    chat_template_sha256: str | None
    verified_capabilities: tuple[str, ...] = ()
    completion_path: str = "/v1/chat/completions"
    timeout_s: float = 120.0
    preferred_admitted_concurrency: int | None = None

    def __post_init__(self) -> None:
        """Validate the complete canary evidence set and fixed deployment identities.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: N is the number of runtime canary evidence digests; each digest must be validated and duplicate evidence rejected before the binding can be trusted.
        """
        for name in ("role", "capability_id", "input_schema_id", "output_schema_id", "deployment_id"):
            value=getattr(self,name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"qualified model binding {name} is required")
        if not self.base_url.strip():
            raise ValueError("qualified model binding route identity is required")
        if self.prompt_generation is not None and (
            type(self.prompt_generation) is not str
            or not self.prompt_generation.strip()
        ):
            raise ValueError(
                "qualified model binding prompt_generation must be non-empty text or None"
            )
        if not self.completion_path.startswith("/"):
            raise ValueError("qualified model binding completion_path must be absolute")
        if (
            isinstance(self.timeout_s, bool)
            or not isinstance(self.timeout_s, (int, float))
            or not math.isfinite(float(self.timeout_s))
            or self.timeout_s <= 0
        ):
            raise ValueError("qualified model binding timeout_s must be finite and positive")
        if type(self.max_admitted_concurrency) is not int or self.max_admitted_concurrency <= 0:
            raise ValueError("qualified model binding concurrency must be positive")
        preferred = self.preferred_admitted_concurrency
        if preferred is not None and (
            type(preferred) is not int
            or preferred <= 0
            or preferred > self.max_admitted_concurrency
        ):
            raise ValueError(
                "qualified model binding preferred concurrency must be "
                "positive and cannot exceed max_admitted_concurrency"
            )
        if type(self.runtime_canary_evidence_digests) is not tuple or not self.runtime_canary_evidence_digests:
            raise ValueError("qualified model binding requires runtime canary evidence digests")
        if len(set(self.runtime_canary_evidence_digests)) != len(self.runtime_canary_evidence_digests):
            raise ValueError("qualified model binding canary evidence digests must be unique")
        for digest in self.runtime_canary_evidence_digests:
            _require_digest(digest, "runtime_canary_evidence_digests[]")
        for field in (
            "deployment_generation",
            "model_stack_digest",
            "qualification_certificate_digest",
            "runtime_qualification_digest",
            "host_identity_digest",
        ):
            _require_digest(getattr(self, field), field)
        if self.tokenizer_sha256 is not None:
            _require_digest(self.tokenizer_sha256, "tokenizer_sha256")
        if self.chat_template_sha256 is not None:
            _require_digest(self.chat_template_sha256, "chat_template_sha256")
        if type(self.verified_capabilities) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in self.verified_capabilities
        ):
            raise TypeError(
                "qualified model binding verified_capabilities must contain non-empty strings"
            )
        normalized_capabilities = tuple(sorted(set(self.verified_capabilities)))
        if len(normalized_capabilities) != len(self.verified_capabilities):
            raise ValueError(
                "qualified model binding verified_capabilities must be unique"
            )
        object.__setattr__(self, "verified_capabilities", normalized_capabilities)
        if self.tokenizer_sha256 is not None and (
            self.model.tokenizer_revision is None
            or not self.model.tokenizer_revision.strip()
        ):
            raise ValueError(
                "qualified tokenizer identity requires model tokenizer_revision"
            )


class QualifiedModelEndpointBindingPort(Protocol):
    """Provider boundary for selecting one already-qualified model role."""

    def binding_for(
        self,
        *,
        role: str,
        capability_id: str,
        input_schema_id: str,
        output_schema_id: str,
        prompt_generation: str | None = None,
    ) -> QualifiedModelEndpointBinding:
        ...


__all__ = ["QualifiedModelEndpointBinding", "QualifiedModelEndpointBindingPort"]
