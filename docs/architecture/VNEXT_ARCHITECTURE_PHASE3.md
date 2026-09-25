# vNext Architecture Phase 3 — Deep Recursive System Decomposition

## Objective

Phase 3 completes the **architecture-first** decomposition. It does not migrate historical implementations. It establishes the destination topology so later migration is a mechanical placement problem rather than a design problem.

## What changed

- Phase 3 originally established 17 top-level systems. Current Trial/Study convergence removes the redundant Scientific top-level authority, leaving 16 canonical top-level systems in the recursive catalog.
- More than one hundred independent boundary nodes are declared.
- Each node exposes the same `api / runtime / providers / composition` seam.
- Each node declares exactly one primary authority and a `must_not_own` boundary.
- Logging is decomposed into context, record schema, routing, sink delivery, storage, query, projection, retention and raw capture.
- Reliability is decomposed into failure taxonomy/descriptor/envelope/fingerprint/catalog/materialization, incident, forensics, diagnostics, recovery and reconciliation.
- Runtime is decomposed so server, process, session, supervision, history and control do not collapse into one runtime manager.
- Model and Environment are decomposed by identity, catalog, assignment/binding, deployment/instance, serving/runtime and request/resolution concerns.

## Migration rule

No historical module should determine the new ownership boundary. The migration order is:

1. choose the destination node from `VNEXT_SYSTEM_CATALOG.json`;
2. define/verify the destination contract;
3. move the authority implementation into the node;
4. move providers behind the node's provider boundary;
5. wire the node only from composition roots;
6. delete the historical ownership boundary;
7. repeat from the parent system downward.

## Debug rule

Every node must be diagnosable by the same coordinates:

`platform → system → subsystem → scope → operation → component → trace/span → authority reference → observation/evidence`

Logging, tracing, telemetry and diagnostics never become a second durable authority.
