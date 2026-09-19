# Downstream Project Repository Contract

## Purpose

Noetrium is an upstream reusable platform. Research methods, benchmark suites, project-specific environment composition, model selections, host inventories, experiment matrices, and scientific results belong in downstream repositories. Reusable providers that serve multiple independent projects may be bundled upstream; Minecraft is one such provider.

The supported relationship is intentionally one-way:

```text
upstream platform repository
        |
        +-- installed as a dependency, or
        +-- forked as a platform baseline
                 |
                 v
       downstream project repository
```

The platform must never import a downstream project. A downstream project may import public platform contracts and bind project-owned providers at its composition root.

## Recommended fork model

For a research program that needs tight integration, fork the upstream platform and keep project additions in isolated project-owned paths rather than editing platform internals.

```text
projects/<project>/
  pyproject.toml        optional independent project package
  src/                  project-owned Python package
  configs/              project-owned experiment/model/deployment config
  docs/                 project-owned scientific and operational docs
  tests/                project-owned regression and live integration tests
```

The downstream project should prefer its own package metadata under the project directory. Keeping project CLI entry points and dependencies out of the upstream root `pyproject.toml` minimizes merge conflicts when syncing upstream.

## Upstream synchronization

A downstream fork should configure remotes as:

```bash
git remote rename origin upstream
git remote add origin <downstream-fork-url>
git fetch upstream
```

Normal synchronization is then:

```bash
git fetch upstream
git merge upstream/master
# or rebase project-only commits when that repository policy allows it
```

Project code should not require edits to `noetrium_platform/` merely to register itself. If a missing generic capability is discovered, implement that capability upstream behind a public contract first, then consume it downstream.

## Dependency rules

Allowed:

```text
downstream project -> noetrium_platform.<system>.api
downstream composition -> public platform composition ports
downstream provider -> platform protocol it implements
```

Forbidden:

```text
noetrium_platform -> downstream project package
platform runtime -> project-specific registry or service locator
downstream project -> platform-private implementation when a public contract exists
```

## Upstream purity gates

The upstream repository must remain independently buildable and testable with no `projects/` directory present. CI should fail if any of these conditions regress:

- root package metadata includes downstream project packages;
- `noetrium_platform/**/*.py` imports a project package;
- the system catalog contains an unapproved downstream environment/project node;
- the upstream Docker image copies project code or installs project-only runtimes;
- release manifests include project-owned paths;
- platform tests require a concrete downstream project fixture.

The canonical automated check is `scripts/platform_repository_boundary.py`.

## Downstream ownership

A downstream repository owns all project-specific scientific truth and operational inventory: project methods, environment adapters that exist only for that project, model choices, host placement, experimental protocols, runbooks, live evidence, and results.

Generic fixes discovered while developing a downstream project should be promoted back upstream only when they can be expressed without importing or naming the project. This keeps the fork thin and makes future upstream synchronization tractable.

## Split milestone

Platform version `0.43.0` establishes the pure-platform repository boundary. Earlier revisions may contain mixed project/platform history; they remain Git history, not current-tree ownership.

## Canonical New Project Experience contract

ROLE 01 owns one project identity/manifest authority for downstream onboarding:

- `noetrium_platform.foundation.portfolio.api.ProjectIdentity`
- `noetrium_platform.foundation.portfolio.api.ProjectManifest`
- `noetrium_platform.foundation.portfolio.api.ProjectCapabilityRequirement`
- `noetrium_platform.foundation.portfolio.api.ProjectConfigurationReference`
- `noetrium_platform.foundation.portfolio.api.ProjectMethodRequirement`
- `encode_project_manifest(...)`
- `decode_project_manifest_bytes(...)` / `decode_project_manifest_document(...)`

`noetrium_platform.foundation.portfolio.project.api` is only a leaf projection of those exact same types. It must not define a second `ProjectDefinition`/manifest identity model.

The manifest wire schema is `noetrium.project-manifest.v2`. The document contains an exact field set plus `semantic_digest`; the digest is computed from the semantic payload without the digest field. Strict decoding rejects unsupported schema versions, duplicate JSON keys, unknown fields, malformed field types, non-canonical identities/digests, non-finite JSON values, and semantic digest drift.

Project-owned facts are kept separate from Platform capability truth:

- `method_requirements` bind each scientific method/treatment to an exact content-addressed implementation digest; `configuration_refs` and `study_ids` are project/scientific configuration references;
- `capability_requirements` are explicit Platform binding inputs and carry capability identity, interface digest, cardinality, and optionality;
- a manifest never selects a concrete Runtime/Model/Environment provider or stores an ambient service-locator key.

A project identity is a composition subject, not a system-registry node. Creating a new project therefore requires no `noetrium_platform/**` edit and no `governance/system_registry/catalog.json` entry.

## Machine-verifiable downstream import policy

`noetrium_platform.foundation.governance.repository_boundary.audit_downstream_project_imports(root)` classifies every Python import in an independent downstream root as one of:

1. `common_platform_api` ? stable common path such as `noetrium_platform.foundation.portfolio.api` or another top-level `<system>.api`;
2. `provider_development_api` ? advanced/leaf contract path such as `noetrium_platform.capabilities.environment.catalog.api` or `noetrium_platform.foundation.governance.architecture.api`;
3. `forbidden_private_implementation` ? Platform imports outside an explicit API package, including Runtime/Provider/Composition implementation paths;
4. `external` ? non-Platform dependencies.

A downstream root that vendors its own `noetrium_platform/` directory is also rejected. Source parse failures are blocking rather than silently omitted. This audit is intended for ROLE 06 `project doctor` / generated-project conformance and for the ROLE 00 clean-room NPE gate.

## ROLE 06 producer handoff

ROLE 06 project creation/doctor must consume the exact Portfolio types/codecs above rather than duplicating manifest parsing or project identity. For advanced composition, the public typed composition contracts are exported from `noetrium_platform.foundation.governance.architecture.api`; generated common-path project code should normally remain on `noetrium_platform.foundation.portfolio.api` plus the producer-owned domain APIs it actually implements/consumes.


Method source provenance is deliberately not a Study facet. Repository/commit
relationships are reproduction provenance, while executable implementation
identity is closed through `ProjectMethodRequirement.implementation_digest`
and the participant binding proof. This separation prevents paper provenance
from masquerading as runtime implementation identity.
