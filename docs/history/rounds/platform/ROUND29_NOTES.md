# Round 29 — Exact Server Runtime Control Plane

This round turns the existing exact runtime state machine into a concrete server control plane.

## Added

- `FrozenDeploymentSet`: role-to-deployment closure and GPU exclusivity audit.
- `RuntimePlatformPorts`: concrete server integration surface with no fallback/model-selection methods.
- `ServerRuntimeAdapter`: exact mapping from the generic runtime transaction to server operations.
- `ServerRuntimeControlPlane`: one entry point for bootstrap/resume with pre-side-effect manifest closure checks.

## Exact execution order

1. verify release
2. verify prompt promotion
3. verify host inventory
4. verify qualified deployment manifests
5. reconcile prior services
6. start exact services
7. verify readiness
8. run role canaries
9. verify method/environment ABI
10. reconcile study
11. start exact study
12. final joined status

A failure in a mutating step is resumed from its explicit reconcile anchor. No alternate model, precision, engine, context length, prompt generation, method ABI, or environment ABI is selected.

## Operational rule

A GPU UUID cannot be assigned to two independent deployment IDs. Roles may share a deployment by pointing to the same deployment ID; they do not cause duplicate model launches.
