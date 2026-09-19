# No Silent Fallback / No Quality Downgrade Policy

The platform must not hide failures by changing scientific or model quality semantics.

Forbidden automatic behaviors include:

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
