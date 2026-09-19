from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json


@dataclass(frozen=True, slots=True)
class PromptCanary:
    canary_id: str
    role: str
    critical: bool
    input_digest: str
    expected_contract: str


@dataclass(frozen=True, slots=True)
class CanarySuite:
    suite_id: str
    canaries: tuple[PromptCanary, ...]
    evaluator_version: str

    def digest(self) -> str:
        raw=json.dumps(asdict(self),sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class CanaryObservation:
    canary_id: str
    prompt_digest: str
    model_resume_key: tuple[object, ...]
    passed: bool
    contract_valid: bool


@dataclass(frozen=True, slots=True)
class PromptQualification:
    suite_digest: str
    prompt_digest: str
    role: str
    model_resume_key: tuple[object,...] | None
    total: int
    passed: int
    critical_total: int
    critical_passed: int
    complete: bool

    @property
    def qualified(self) -> bool:
        return self.complete and self.total == self.passed and self.critical_total == self.critical_passed and self.model_resume_key is not None


def evaluate_canaries(suite: CanarySuite, role: str, prompt_digest: str, observations: tuple[CanaryObservation, ...], *, expected_model_resume_key: tuple[object, ...] | None = None) -> PromptQualification:
    expected=[c for c in suite.canaries if c.role==role]
    obs={o.canary_id:o for o in observations}
    model_keys={o.model_resume_key for o in observations}
    observed_model=next(iter(model_keys)) if len(model_keys)==1 else None
    model_consistent=observed_model is not None and (expected_model_resume_key is None or observed_model==expected_model_resume_key)
    complete=(len(obs)==len(observations) and set(obs)=={c.canary_id for c in expected} and model_consistent)
    def valid(c: PromptCanary) -> bool:
        o=obs.get(c.canary_id)
        return bool(o and o.passed and o.contract_valid and o.prompt_digest==prompt_digest and model_consistent)
    passed=sum(1 for c in expected if valid(c)); critical=[c for c in expected if c.critical]; critical_passed=sum(1 for c in critical if valid(c))
    return PromptQualification(suite.digest(),prompt_digest,role,observed_model,len(expected),passed,len(critical),critical_passed,complete)
