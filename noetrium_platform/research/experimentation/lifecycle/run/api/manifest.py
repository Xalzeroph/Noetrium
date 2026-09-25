"""Immutable identity of one exact experiment/run launch."""

from __future__ import annotations

from dataclasses import dataclass
from noetrium_platform.research.experimentation.identity import RunResearchSemanticsReference
from noetrium_platform.foundation.kernel.kernel import canonical_digest


_HEX = frozenset("0123456789abcdef")


def _require_non_empty_string(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _require_sha256(value: object, field: str) -> str:
    if type(value) is not str or len(value) != 64 or any(ch not in _HEX for ch in value):
        raise ValueError(f"{field} must be lowercase SHA-256")
    return value


def _require_unique(values: tuple[object, ...], field: str) -> None:
    try:
        unique = set(values)
    except TypeError as exc:
        raise ValueError(f"{field} values must be hashable") from exc
    if len(values) != len(unique):
        raise ValueError(f"{field} values must be unique")


@dataclass(frozen=True, slots=True, order=True)
class CompositionPlanReference:
    """The identity and digest of one composition plan frozen into a run.

    The launch manifest records composition provenance as immutable metadata;
    it does not embed providers or expose a capability resolver.
    """

    composition_id: str
    owner_key: str
    scope_key: str
    plan_digest: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.composition_id, "composition plan reference composition_id")
        _require_non_empty_string(self.owner_key, "composition plan reference owner_key")
        _require_non_empty_string(self.scope_key, "composition plan reference scope_key")
        _require_sha256(self.plan_digest, "composition plan reference plan_digest")


def _validate_command_argv(command_argv: tuple[str, ...]) -> None:
    if type(command_argv) is not tuple or not command_argv:
        raise ValueError("run launch manifest command argv is required")
    if any(type(value) is not str for value in command_argv):
        raise ValueError("run launch manifest command argv values must be strings")
    if not command_argv[0].strip():
        raise ValueError("run launch manifest command argv is required")


def _validate_config_digests(rows: tuple[tuple[str, str], ...]) -> None:
    if type(rows) is not tuple:
        raise ValueError("run launch manifest config_digests must be a tuple")
    names: list[str] = []
    for row in rows:
        if type(row) is not tuple or len(row) != 2:
            raise ValueError("run launch manifest config digest must be a pair")
        name, digest = row
        _require_non_empty_string(name, "run launch manifest configuration name")
        _require_non_empty_string(digest, "run launch manifest configuration digest")
        names.append(name)
    _require_unique(tuple(names), "run launch manifest configuration identities")


def _validate_composition_plans(plans: tuple[CompositionPlanReference, ...]) -> None:
    if type(plans) is not tuple or not plans:
        raise ValueError("run launch manifest requires at least one composition plan")
    if any(type(row) is not CompositionPlanReference for row in plans):
        raise ValueError("run launch manifest composition plans must be typed references")
    if plans != tuple(sorted(plans)):
        raise ValueError("run launch manifest composition plans must be canonically ordered")
    keys = tuple((row.composition_id, row.owner_key, row.scope_key) for row in plans)
    _require_unique(keys, "run launch manifest composition plan identities")


@dataclass(frozen=True, slots=True)
class RunLaunchManifest:
    """Single frozen launch authority for experiment, runtime, and recovery.

    This record joins release, prompt, model, host, participant, experiment,
    command, configuration, seed, and composition-plan identities. Runtime
    control consumes it; it does not own a second manifest shape.
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
    project_manifest_digest: str
    experiment_spec_digest: str
    research_semantics: RunResearchSemanticsReference
    command_argv: tuple[str, ...]
    launcher_binary_sha256: str
    command_environment_digest: str
    config_digests: tuple[tuple[str, str], ...]
    seed_identity: str
    composition_plans: tuple[CompositionPlanReference, ...]

    def __post_init__(self) -> None:
        required = (
            ("release_digest", self.release_digest),
            ("prompt_generation_digest", self.prompt_generation_digest),
            ("prompt_promotion_digest", self.prompt_promotion_digest),
            ("role_model_manifest_digest", self.role_model_manifest_digest),
            ("target_host_identity_digest", self.target_host_identity_digest),
            ("participant_implementation_inventory_digest", self.participant_implementation_inventory_digest),
            ("participant_runtime_inventory_digest", self.participant_runtime_inventory_digest),
            ("participant_binding_manifest_digest", self.participant_binding_manifest_digest),
            ("experiment_spec_digest", self.experiment_spec_digest),
            ("seed_identity", self.seed_identity),
        )
        for field, value in required:
            _require_non_empty_string(value, f"run launch manifest {field}")
        _require_sha256(self.project_manifest_digest, "run launch manifest project_manifest_digest")
        if type(self.research_semantics) is not RunResearchSemanticsReference:
            raise TypeError("run launch manifest research_semantics must be RunResearchSemanticsReference")
        _validate_command_argv(self.command_argv)
        _require_sha256(self.launcher_binary_sha256, "run launch manifest launcher binary digest")
        _require_sha256(self.command_environment_digest, "run launch manifest command environment digest")
        if type(self.qualified_deployment_digests) is not tuple or any(
            type(value) is not str for value in self.qualified_deployment_digests
        ):
            raise ValueError("run launch manifest deployment digests must be strings")
        _require_unique(self.qualified_deployment_digests, "run launch manifest deployment digests")
        _validate_config_digests(self.config_digests)
        _validate_composition_plans(self.composition_plans)

    @property
    def research_semantics_digest(self) -> str:
        return self.research_semantics.digest()

    @property
    def composition_plan_digest(self) -> str:
        """Aggregate all frozen composition evidence into one run identity field."""

        return canonical_digest(self.composition_plans)

    def digest(self) -> str:
        return canonical_digest(self)


__all__ = ["CompositionPlanReference", "RunLaunchManifest", "RunResearchSemanticsReference"]
