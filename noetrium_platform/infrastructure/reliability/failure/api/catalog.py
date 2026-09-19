from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from .contracts import RecoveryAction, RiskLevel


@dataclass(frozen=True, slots=True)
class FailureSpec:
    domain: str
    code: str
    stage: str
    default_recovery: RecoveryAction
    data_integrity_risk: RiskLevel = RiskLevel.NONE
    comparability_risk: RiskLevel = RiskLevel.NONE
    scientific_validity_risk: RiskLevel = RiskLevel.NONE
    description: str = ""
    owner: str = ""
    diagnostic_focus: tuple[str, ...] = ()
    operator_checks: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.domain, self.code, self.stage)

    def digest(self) -> str:
        raw = json.dumps(
            asdict(self),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class FailureCatalog:
    """Central stable taxonomy. Runtime code should not invent free-form failure strings on hot paths."""

    def __init__(self, specs: tuple[FailureSpec, ...] = ()) -> None:
        self._specs: dict[tuple[str, str, str], FailureSpec] = {}
        self._codes: dict[tuple[str, str], FailureSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: FailureSpec) -> None:
        if not spec.domain or spec.domain.upper()!=spec.domain:
            raise ValueError(f"failure domain must be stable UPPER_SNAKE: {spec.domain}")
        if not spec.code or spec.code.upper()!=spec.code:
            raise ValueError(f"failure code must be stable UPPER_SNAKE: {spec.code}")
        if not spec.stage or any(ch.isspace() for ch in spec.stage):
            raise ValueError(f"failure stage must be stable space-free token: {spec.stage}")
        if spec.key in self._specs:
            raise ValueError(f"duplicate failure spec: {spec.key}")
        code_key=(spec.domain,spec.code)
        prior=self._codes.get(code_key)
        if prior is not None and prior!=spec:
            raise ValueError(
                f"failure code semantic drift for {code_key}: "
                f"existing stage={prior.stage} new stage={spec.stage}"
            )
        self._specs[spec.key] = spec
        self._codes[code_key] = spec

    def get(self, domain: str, code: str, stage: str) -> FailureSpec | None:
        return self._specs.get((domain, code, stage))

    def require(self, domain: str, code: str, stage: str) -> FailureSpec:
        spec = self.get(domain, code, stage)
        if spec is None:
            raise KeyError(f"unknown failure taxonomy: {(domain, code, stage)}")
        return spec

    def all(self) -> tuple[FailureSpec, ...]:
        return tuple(sorted(self._specs.values(), key=lambda x: x.key))

    def find(
        self,
        *,
        domain: str | None = None,
        code: str | None = None,
    ) -> tuple[FailureSpec, ...]:
        specs = self.all()
        if domain is not None:
            specs = tuple(x for x in specs if x.domain == domain)
        if code is not None:
            specs = tuple(x for x in specs if x.code == code)
        return specs

    def knowledge_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        for spec in self.all():
            prefix = f"{spec.domain}:{spec.code}:{spec.stage}"
            if not spec.description.strip():
                errors.append(f"{prefix}: missing description")
            if not spec.owner.strip():
                errors.append(f"{prefix}: missing owner")
            if not spec.diagnostic_focus:
                errors.append(f"{prefix}: missing diagnostic_focus")
            if not spec.operator_checks:
                errors.append(f"{prefix}: missing operator_checks")
        return tuple(errors)

__all__ = ["FailureCatalog", "FailureSpec"]
