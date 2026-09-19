# Minecraft runtime bootstrap and source scenarios

## Purpose

The bundled Minecraft environment separates independently replaceable concerns:

1. immutable server artifact acquisition;
2. verified Java toolchain acquisition and materialization;
3. exact Java service lifecycle and readiness;
4. source-world scenario provisioning and world cuts;
5. Mineflayer participant actions and evidence.

Downstream applications select these interfaces at their composition root. The upstream provider owns only reusable Minecraft contracts, runtime semantics and adapters; benchmark/task meaning remains downstream.

## Official server artifact route

`compose_official_minecraft_server_artifacts()` binds official version metadata to the generic streaming artifact acquirer. Acquisition enforces published hashes/size, temporary download followed by atomic publication, verified reuse, and fail-closed mismatch handling.

The resulting receipt records source identity, content digests, byte size and producer operation identity. Server acquisition is explicit; a missing artifact is never silently replaced by an untracked download.

## Verified Java runtime route

`compose_eclipse_adoptium_java_runtime()` combines the Adoptium metadata adapter, generic atomic artifact acquisition and bounded safe archive materialization.

The materializer rejects absolute/parent-traversing paths, duplicate members, devices/FIFOs, unsafe links, missing required files, member-count overflow and expanded-size overflow. It publishes a complete tree only by same-filesystem rename.

The Java adapter then verifies the requested major version with `java -version` and records archive, tree, executable and version-output identities. Callers may instead provide an already-qualified Java executable.

## Endpoint reservation and bind proof

Endpoint allocation and service readiness are separate authorities. A branch server receives
a resource allocation in `RESERVED` state. After the exact server contract returns a typed
`ServiceReadyObservation`, the Minecraft runtime submits an `EndpointBindingProof` containing
the allocation identity, exact endpoint, current fencing token, process/environment binder
identity and readiness evidence reference. Only Resource may persist `RESERVED -> BOUND`.

When RCON is enabled, the server readiness observation covers the configured server and RCON
readiness contract, and both exact allocations must be confirmed. If any bind proof is rejected
or becomes stale, branch startup fails and the startup transaction stops the server and releases
all allocations; no partially bound endpoint is exposed as a live branch runtime.

## Typed source-world scenarios

`MinecraftScenarioSpec` is an ordered immutable set of `MinecraftScenarioStep` values. Each step declares a mutation command and a required response assertion, optionally verified through a separate command.

`RconMinecraftScenarioProvisioner` applies steps only after TCP and RCON readiness. It records canonical step identity plus mutation/verification evidence. Any missing assertion, RCON error or incomplete receipt aborts startup so a partially prepared world cannot leak into a source cut.

Scenario identity participates in environment/source generation. The scenario itself is an application input; the provider does not own a particular benchmark scenario.

## Qualification layers

Provider qualification is intentionally layered:

- Python contract/runtime tests validate task types, world cuts, readiness and action evidence without a live server.
- `node --test actions.test.js` validates the locked Mineflayer bridge against installed JavaScript dependencies.
- `minecraft-doctor` validates the optional container runtime (Java, Node and bridge dependencies).
- A live server qualification validates real server readiness, RCON provisioning, bot login and bounded external effects.

A live qualification proves infrastructure capability only. Scientific interpretation belongs to the downstream experiment that consumes the provider.

## Ownership boundary

Upstream owns Minecraft server/runtime adapters, typed action contracts, scenario/world-cut mechanisms and provider qualification. Downstream repositories own task manifests, benchmark normalization, experiment matrices, scientific success criteria and result interpretation.

## Bridge startup diagnostics

The JSONL transport keeps a bounded provider `stderr` tail and surfaces the latest lines when the bridge exits or closes stdout before protocol readiness. Diagnostic formatting snapshots the deque through the immutable tuple projection before tail slicing, so an error-reporting path cannot mask the original Mineflayer/provider failure with a container-type error. `test_minecraft_jsonl_transport_v1.py` guards this failure path.
