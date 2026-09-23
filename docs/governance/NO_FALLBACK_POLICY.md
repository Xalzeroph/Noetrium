# No Runtime Fallback / No Quality Downgrade Policy

The platform must fail closed rather than continue by changing scientific, provider, execution, or model-quality semantics. Runtime fallback is forbidden even when it would be explicit or operator-approved; changing a frozen binding creates a new revision and a new admitted execution.

Forbidden runtime substitution behaviors include:

- substitute a smaller or different LLM;
- change model revision;
- lower dtype/quantization quality;
- shorten context length;
- remove tools/capabilities;
- silently skip required prompt blocks;
- switch to a weaker verifier;
- discard logs because a sink is unhealthy;
- continue a scientific run after evidence integrity is unknown;
- treat an unknown external effect as definitely failed and replay it blindly.

Allowed recovery actions preserve identity and semantics:

- reconnect/restart the same process/configuration;
- exact request retry when the side effect is proven absent/idempotent;
- reconcile an unknown effect before deciding;
- restore a verified checkpoint;
- rebuild derived/cache/index state from authoritative evidence;
- pause/quarantine when correctness cannot be proven.


## Binding changes are new executions

A runtime may recover only while preserving the frozen identity and semantics of the
accepted execution. Reconnecting the same qualified provider, restoring the same
verified checkpoint, or retrying the exact same request after proving that no external
effect occurred are recovery actions.

Changing any frozen model, provider, endpoint identity, precision, quantization,
context budget, prompt program, capability set, environment, dataset cut, verifier,
method, workload, seed policy, acceptance rule, or other scientific dependency is not
recovery. It requires a new explicit revision, fresh qualification/admission, and a new
execution identity. The original execution remains immutable historical truth.

There is no "best available", "next provider", "weaker verifier", reduced-quality,
compatibility, or emergency runtime path. Missing or invalid bindings fail closed.
