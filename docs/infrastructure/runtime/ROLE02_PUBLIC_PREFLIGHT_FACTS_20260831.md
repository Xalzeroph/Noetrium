# ROLE02 public preflight facts — 2026-08-31

This note closes the ROLE02-owned NPE question of whether doctor/compiler preflight needs a new runtime/resource/recovery state authority. It does not.

The public domain facts required by a downstream read-only consumer are:

- Runtime: `runtime.server.health.api.ServerDiagnosticReport` and its typed status/issues.
- Resource: `resource.compute.api.ComputeRequirement`, `ComputeHost`, and the read-only `ComputeCandidatePort`.
- Reliability: `reliability.recovery.api.RecoveryDecisionReport` and typed recommendations.
- Scope identity remains supplied by the existing `scope.api` authority.

`ComputeCandidatePort` exposes only `candidates(requirement, scope=...)`. The existing `ComputeSchedulerPort` extends that read-only protocol with allocation/release authority, so preflight can depend on the narrower type without receiving mutation capability.

`tests/test_runtime_preflight_public_contract_v1.py` proves the public facts are sufficient for candidate placement, runtime readiness and recovery blocking using only `*.api` imports; it also proves the candidate port has no allocate/release methods.

These facts remain producer-owned domain truth. ROLE02 must not add `InfrastructureState`, a generic transition enum, a service locator, or a project-owned durable preflight store.