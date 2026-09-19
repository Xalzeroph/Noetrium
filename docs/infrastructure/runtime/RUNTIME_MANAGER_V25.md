# Runtime Manager v25

The platform now has one top-level exact startup/resume transaction driven by
the experiment-owned `experimentation/run/manifest/api.RunLaunchManifest`.
Runtime control consumes only its `RuntimeLaunchManifestPort`; it does not
define, re-export, or import a second concrete runtime manifest.

The manifest binds release, promoted Prompt generation, Prompt promotion
evidence, role-model manifest, exact qualified deployments, target-host
inventory, method/environment identities and ABIs, Study spec, exact
controller argv, launcher binary identity, controller-environment digest,
capability-composition-plan references, config digests and seed identity.

The single plan is:

1. verify release;
2. verify Prompt promotion;
3. verify target-host inventory;
4. verify exact qualified deployments;
5. reconcile prior service processes;
6. start exact services;
7. verify READY;
8. run exact role canaries;
9. verify Method/Environment ABI;
10. reconcile prior Study writer;
11. start exact Study;
12. final joined status.

Every transition is durably written before execution. If the controller crashes during a mutating service/Study start, the next invocation rewinds to its explicit reconciliation step instead of replaying the side effect. Non-mutating verification failures retry that exact step.

There is no alternate-model branch, Prompt fallback, context reduction or method substitution in the plan.
