from __future__ import annotations

"""Derived execution-view ProjectManifest composition.

The filesystem ProjectManifest remains project identity/tool provenance. Scientific
requirements are derived from the frozen research.study NoetriumUnit,
so downstream projects never repeat Method/Study capability declarations.
"""

from dataclasses import dataclass, field
from collections.abc import Mapping
from types import MappingProxyType
from threading import RLock

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.portfolio.api import (
    project_capability_requirement_unit,
    project_configuration_reference_unit,
    project_manifest_capability_requirements,
    project_manifest_configuration_refs,
    project_manifest_description,
    project_manifest_method_requirements,
    project_manifest_name,
    project_manifest_program_id,
    project_manifest_project_id,
    project_manifest_provenance,
    project_manifest_provider_bindings,
    project_manifest_study_ids,
    project_manifest_tags,
    project_manifest_template_revision,
    project_manifest_unit,
    project_manifest_version,
    project_method_requirement_unit,
    project_provider_binding_unit,
    require_project_manifest,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.product.research_traits import TRAIT_CONFIGURATION
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    require_study_unit,
    study_binding_requirement_digest,
    study_binding_requirements,
    study_definition_digest,
    study_id,
    study_project_id,
)
from noetrium_platform.research.experimentation.binding import (
    binding_requirements_participants,
    binding_requirements_trial_provider,
    participant_requirement_method_id,
    participant_requirement_treatment_id,
)

from .research_binding_authority import (
    ResearchProjectManifestResolverPort,
    research_project_manifest_capability_ids,
    research_project_manifest_configuration_ids,
    research_project_manifest_method_keys,
    research_project_manifest_requirement,
)
from .research_method_participant_binding import (
    exact_method_programs,
    exact_method_requirement_implementation_digest,
)

_AUTO_WORKLOAD_PROVIDER = "noetrium.auto.workload"
_PROVIDER_VERSION = "1"


def _requirement_parts(requirement_id: str) -> tuple[str, str]:
    if type(requirement_id) is not str or not requirement_id.strip():
        raise ValueError("research capability requirement id must be non-empty")
    if "." in requirement_id:
        namespace, name = requirement_id.split(".", 1)
        return namespace, name
    return "research", requirement_id


def _capability_requirement(
    requirement_id: str,
    *,
    graph_digest: str,
    binding_requirement_digest: str,
) -> NoetriumUnit:
    namespace, name = _requirement_parts(requirement_id)
    return project_capability_requirement_unit(
        requirement_id,
        namespace,
        name,
        1,
        canonical_digest(
            {
                "schema": "noetrium.derived-capability-requirement.v1",
                "requirement_id": requirement_id,
                "graph_digest": graph_digest,
                "binding_requirement_digest": binding_requirement_digest,
            }
        ),
    )


def derive_research_project_manifest(
    base: NoetriumUnit,
    program: NoetriumUnit,
    definition: NoetriumUnit,
    *,
    method_programs: Mapping[str, object] | None = None,
) -> NoetriumUnit:
    """Derive the exact execution-view manifest required by one Study."""

    require_project_manifest(base)
    if type(program) is not NoetriumUnit:
        raise TypeError("derived research manifest requires NoetriumUnit")
    require_study_unit(definition)
    if project_manifest_project_id(base) != study_project_id(definition):
        raise ValueError(
            "derived research manifest project identity differs from Study"
        )

    requirement = research_project_manifest_requirement(definition)
    graph_digest = program.unit_digest
    capabilities = tuple(
        _capability_requirement(
            requirement_id,
            graph_digest=graph_digest,
            binding_requirement_digest=study_binding_requirement_digest(definition),
        )
        for requirement_id in research_project_manifest_capability_ids(requirement)
    )

    trial_requirement = binding_requirements_trial_provider(study_binding_requirements(definition))
    provider_bindings = ()
    if trial_requirement in research_project_manifest_capability_ids(requirement):
        provider_bindings = (
            project_provider_binding_unit(
                "auto.trial",
                trial_requirement,
                _AUTO_WORKLOAD_PROVIDER,
                _PROVIDER_VERSION,
                canonical_digest(
                    {
                        "schema": "noetrium.derived-workload-trial-provider.v1",
                        "graph_digest": graph_digest,
                        "study_digest": study_definition_digest(definition),
                    }
                ),
            ),
        )

    participant_by_key = {
        (participant_requirement_method_id(row), participant_requirement_treatment_id(row)): row
        for row in binding_requirements_participants(study_binding_requirements(definition))
    }
    methods: list[NoetriumUnit] = []
    for method_id, treatment_id in research_project_manifest_method_keys(requirement):
        participant = participant_by_key.get((method_id, treatment_id))
        if participant is None:
            raise ValueError(
                "Study manifest method key has no participant requirement: "
                f"{method_id!r}/{treatment_id!r}"
            )
        methods.append(
            project_method_requirement_unit(
                method_id,
                treatment_id,
                exact_method_requirement_implementation_digest(
                    program,
                    participant,
                    method_programs=method_programs,
                ),
            )
        )

    configurations: list[NoetriumUnit] = []
    for config_id in research_project_manifest_configuration_ids(requirement):
        try:
            config_definition = program.symbol(config_id)
        except LookupError as exc:
            raise LookupError(
                "NoetriumUnit has no exact CONFIGURATION definition for "
                f"configuration_id={config_id!r}"
            ) from exc
        if not config_definition.has_trait(TRAIT_CONFIGURATION):
            raise LookupError(
                "NoetriumUnit symbol is not research.configuration for "
                f"configuration_id={config_id!r}"
            )
        configurations.append(
            project_configuration_reference_unit(
                config_id,
                (
                    "research-graph://"
                    + graph_digest
                    + "/configuration/"
                    + config_id
                ),
                config_definition.symbol_digest,
            )
        )

    return project_manifest_unit(
        project_manifest_project_id(base),
        project_manifest_version(base),
        project_manifest_program_id(base),
        project_manifest_name(base),
        description=project_manifest_description(base),
        tags=project_manifest_tags(base),
        template_revision=project_manifest_template_revision(base),
        provenance=project_manifest_provenance(base),
        capability_requirements=capabilities,
        provider_bindings=provider_bindings,
        method_requirements=tuple(methods),
        configuration_refs=tuple(configurations),
        study_ids=(study_id(definition),),
    )


@dataclass(frozen=True, slots=True)
class PortfolioDerivedProjectManifestResolver:
    """Resolve Study ownership across one or many project manifests.

    Project cardinality is not an execution mode.  Every Study selects exactly
    one filesystem ProjectManifest by its frozen project_id, then exactly one
    NoetriumUnit program by Method ownership.  A one-project portfolio is the
    same relation with a manifest tuple of length one.
    """

    bases: tuple[NoetriumUnit, ...]
    programs: tuple[tuple[str, tuple[str, ...], NoetriumUnit], ...]
    _bases_by_project: object = field(init=False, repr=False, compare=False)
    _programs_by_project: object = field(init=False, repr=False, compare=False)
    _programs_by_project_method: object = field(init=False, repr=False, compare=False)
    _scopes_by_program_identity: object = field(init=False, repr=False, compare=False)
    _methods_by_program_identity: object = field(init=False, repr=False, compare=False)
    _program_owner_cache: dict[tuple[str, frozenset[str]], NoetriumUnit] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _program_owner_by_study_digest: dict[str, NoetriumUnit] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _program_owner_cache_lock: object = field(
        default_factory=RLock, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if (
            type(self.bases) is not tuple
            or not self.bases
            or any(type(row) is not NoetriumUnit for row in self.bases)
        ):
            raise TypeError(
                "derived manifest resolver requires non-empty ProjectManifest tuple"
            )
        for row in self.bases:
            require_project_manifest(row)
        project_ids = tuple(
            project_manifest_project_id(row) for row in self.bases
        )
        if len(project_ids) != len(set(project_ids)):
            raise ValueError(
                "derived manifest resolver project identities must be unique"
            )
        if (
            type(self.programs) is not tuple
            or not self.programs
            or any(
                type(row) is not tuple
                or len(row) != 3
                or type(row[0]) is not str
                or not row[0].strip()
                or type(row[1]) is not tuple
                or not row[1]
                or any(type(part) is not str or not part.strip() for part in row[1])
                or type(row[2]) is not NoetriumUnit
                for row in self.programs
            )
        ):
            raise TypeError(
                "derived manifest resolver requires non-empty "
                "(project_id, graph_path, NoetriumUnit) tuple"
            )
        known_projects = set(project_ids)
        unknown_projects = tuple(
            sorted({project_id for project_id, _path, _program in self.programs} - known_projects)
        )
        if unknown_projects:
            raise ValueError(
                "derived manifest resolver program ownership references unknown "
                f"projects: {unknown_projects!r}"
            )

        # Immutable Units make ownership indexing safe for the resolver lifetime.
        # Method implementations are reconstructed exactly once per program;
        # hot Study binding paths never repeat Python source/materialization work.
        bases_by_project = {
            project_manifest_project_id(row): row for row in self.bases
        }
        programs_by_project: dict[
            str, list[tuple[frozenset[str], NoetriumUnit]]
        ] = {}
        programs_by_project_method: dict[
            str, dict[str, list[tuple[frozenset[str], NoetriumUnit]]]
        ] = {}
        scopes_by_program_identity: dict[int, list[str]] = {}
        methods_by_program_identity: dict[int, object] = {}
        for project_id, path, program in self.programs:
            methods = exact_method_programs(program)
            methods_by_program_identity[id(program)] = MappingProxyType(dict(methods))
            method_ids = frozenset(methods)
            program_row = (method_ids, program)
            programs_by_project.setdefault(project_id, []).append(program_row)
            method_postings = programs_by_project_method.setdefault(project_id, {})
            for method_id in method_ids:
                method_postings.setdefault(method_id, []).append(program_row)
            scopes_by_program_identity.setdefault(id(program), []).append(
                "::".join(path)
            )
        object.__setattr__(
            self,
            "_bases_by_project",
            MappingProxyType(bases_by_project),
        )
        object.__setattr__(
            self,
            "_programs_by_project",
            MappingProxyType({
                project_id: tuple(rows)
                for project_id, rows in programs_by_project.items()
            }),
        )
        object.__setattr__(
            self,
            "_programs_by_project_method",
            MappingProxyType({
                project_id: MappingProxyType({
                    method_id: tuple(rows)
                    for method_id, rows in postings.items()
                })
                for project_id, postings in programs_by_project_method.items()
            }),
        )
        object.__setattr__(
            self,
            "_scopes_by_program_identity",
            MappingProxyType({
                key: tuple(rows)
                for key, rows in scopes_by_program_identity.items()
            }),
        )
        object.__setattr__(
            self,
            "_methods_by_program_identity",
            MappingProxyType(methods_by_program_identity),
        )

    def method_programs_for(self, program: NoetriumUnit) -> Mapping[str, object]:
        if type(program) is not NoetriumUnit:
            raise TypeError("method ownership lookup requires NoetriumUnit")
        methods = self._methods_by_program_identity.get(id(program))
        if methods is None:
            raise LookupError("NoetriumUnit program is outside this portfolio resolver")
        return methods

    def base_for(self, definition: NoetriumUnit) -> NoetriumUnit:
        require_study_unit(definition)
        project_id = study_project_id(definition)
        manifest = self._bases_by_project.get(project_id)
        if manifest is None:
            raise LookupError(
                "Study does not resolve to exactly one ProjectManifest: "
                f"project_id={project_id!r} matches=0"
            )
        return manifest

    def program_for(self, definition: NoetriumUnit) -> NoetriumUnit:
        """Resolve the unique Program owning one Study's Method closure.

        The lower bound is Ω(R) to read the R required Method identities.
        An inverted Method→Program index restricts containment checks to the
        rarest posting list, and immutable closure results are memoized by
        (project, required-method-set). Repeated owner lookups are therefore
        O(1) after the caller has formed the same immutable requirement key.
        """
        require_study_unit(definition)
        study_digest = definition.unit_digest
        with self._program_owner_cache_lock:
            cached_by_study = self._program_owner_by_study_digest.get(study_digest)
        if cached_by_study is not None:
            return cached_by_study

        project_id = study_project_id(definition)
        required_method_ids = frozenset(
            participant_requirement_method_id(row)
            for row in binding_requirements_participants(
                study_binding_requirements(definition)
            )
        )
        cache_key = (project_id, required_method_ids)
        with self._program_owner_cache_lock:
            cached = self._program_owner_cache.get(cache_key)
            if cached is not None:
                study_cached = self._program_owner_by_study_digest.setdefault(
                    study_digest, cached
                )
            else:
                study_cached = None
        if study_cached is not None:
            if study_cached.unit_digest != cached.unit_digest:
                raise RuntimeError(
                    "immutable Study identity resolved to multiple owning Programs"
                )
            return study_cached

        if required_method_ids:
            postings = self._programs_by_project_method.get(project_id, {})
            candidate_rows = tuple(
                postings.get(method_id, ())
                for method_id in required_method_ids
            )
            if any(not rows for rows in candidate_rows):
                matches = ()
            else:
                rarest = min(candidate_rows, key=len)
                matches = tuple(
                    program
                    for method_ids, program in rarest
                    if required_method_ids.issubset(method_ids)
                )
        else:
            matches = tuple(
                program
                for _method_ids, program in self._programs_by_project.get(
                    project_id, ()
                )
            )
        if len(matches) != 1:
            raise LookupError(
                "Study does not resolve to exactly one NoetriumUnit by Method "
                f"ownership: study={study_id(definition)!r} matches="
                f"{tuple(row.unit_id for row in matches)!r}"
            )
        resolved = matches[0]
        with self._program_owner_cache_lock:
            existing = self._program_owner_cache.setdefault(cache_key, resolved)
            study_existing = self._program_owner_by_study_digest.setdefault(
                study_digest, existing
            )
        if existing is not resolved and existing.unit_digest != resolved.unit_digest:
            raise RuntimeError(
                "immutable Study Method closure resolved to multiple Programs"
            )
        if (
            study_existing is not existing
            and study_existing.unit_digest != existing.unit_digest
        ):
            raise RuntimeError(
                "immutable Study identity resolved to multiple owning Programs"
            )
        return study_existing

    def scope_id_for_program(self, program: NoetriumUnit) -> str:
        if type(program) is not NoetriumUnit:
            raise TypeError("program scope lookup requires NoetriumUnit")
        matches = self._scopes_by_program_identity.get(id(program), ())
        if len(matches) != 1:
            raise LookupError(
                "NoetriumUnit program does not resolve to exactly one canonical path"
            )
        return matches[0]

    def _program(self, definition: NoetriumUnit) -> NoetriumUnit:
        return self.program_for(definition)

    def resolve(self, definition: NoetriumUnit) -> NoetriumUnit:
        require_study_unit(definition)
        program = self._program(definition)
        return derive_research_project_manifest(
            self.base_for(definition),
            program,
            definition,
            method_programs=self.method_programs_for(program),
        )


assert isinstance(
    PortfolioDerivedProjectManifestResolver,
    type,
)

__all__ = [
    "PortfolioDerivedProjectManifestResolver",
    "derive_research_project_manifest",
]
