# Noetrium Runtime and Deployment

This document is the detailed operational companion to the system architecture. It consolidates server deployment, Docker, environment isolation, model serving, resource ownership, scheduling, crash recovery, and shutdown behavior for Noetrium 1.0.

Runtime optimization never changes the scientific contract: immutable realizations may be shared, mutable experiment state is isolated, and physical effects remain fenced by their owning authorities.

## Docker-first server deployment and large-scale execution

For Linux server execution, the intended host contract is Docker plus Compose. Host Python is not required for the canonical deployment path; control-plane Python executes inside the bootstrap container.

### 1. Host prerequisites

The ordinary deployment user must be able to run:

~~~bash
docker info
docker compose version
~~~

The canonical launcher never invokes sudo.

GPU hosts must already have a working NVIDIA driver and Docker GPU runtime. Noetrium does not mutate the host driver.

<code>deploy/install_workspace_docker_engine.sh</code> can install Docker binaries into the workspace, but starting that bundled rootful daemon requires host privileges. For an ordinary-user deployment, prefer the rootless manager described below. Rootless Docker still requires <code>dockerd-rootless.sh</code>, RootlessKit, slirp4netns, setuid <code>newuidmap/newgidmap</code>, subordinate UID/GID ranges and enabled unprivileged user namespaces. Noetrium checks these prerequisites and fails closed; it never emulates the privileged UID/GID mapping helpers in user space.

On a shared server, inspect current GPU and host load before launch. Existing foreign workloads are external ownership facts and must not be killed or preempted merely to make room for Noetrium.

### 2. Put mutable deployment state on the data disk

Redirect runtime state away from a small system partition:

~~~bash
export NOETRIUM_DEPLOYMENT_STATE_ROOT=/data/noetrium-runtime
mkdir -p "$NOETRIUM_DEPLOYMENT_STATE_ROOT"
~~~

The launcher uses:

~~~text
$NOETRIUM_DEPLOYMENT_STATE_ROOT/
├── environment-images/
└── reproduction-fleet/
~~~

Large model caches, world state and scientific outputs should likewise use an explicitly selected data volume.

This variable does **not** relocate the Docker daemon's own image/layer store. Before building on a server with a small system disk, inspect the active daemon storage:

~~~bash
docker info --format '{{.DockerRootDir}}'
~~~

If that path is on a nearly-full system partition, fix the daemon/rootless-Docker data root first. Otherwise image pulls and builds can still consume the system disk even though Noetrium state is on a data volume.

Noetrium can own a user-level rootless Docker daemon entirely on the selected data volume:

~~~bash
export NOETRIUM_DEPLOYMENT_STATE_ROOT=/data/noetrium-runtime
export NOETRIUM_DOCKER_DATA_ROOT=/data/noetrium-runtime/docker
export NOETRIUM_DOCKER_RUNTIME_ROOT=/data/noetrium-runtime/docker-runtime

./deploy/noetrium infra docker doctor
./deploy/noetrium infra docker start
eval "$(./deploy/noetrium infra docker env)"
./deploy/noetrium infra docker status
./deploy/noetrium infra doctor
~~~

When <code>NOETRIUM_DOCKER_DATA_ROOT</code> is set, normal deployment doctor/build/run paths verify that the active daemon's actual <code>DockerRootDir</code> equals that canonical path. A variable pointing at a data disk is not accepted as proof that Docker really moved. Stop only the exact user-owned daemon with <code>./deploy/noetrium infra docker stop</code>.

If <code>docker doctor</code> reports a missing privileged host prerequisite such as <code>newuidmap</code>, an administrator must install or enable that prerequisite once. Do not fall back to a nearly-full system DockerRootDir merely to continue a run.

The current evidence-bound image builder also requires real Git source metadata. It derives the source identity with Git and refuses a dirty checkout before building the qualified wheel/image. A source-only archive with no .git metadata is not currently sufficient for the formal image-build path. When transporting source without GitHub, preserve the repository metadata by copying the complete checkout or by using a verified Git bundle/local transport. Do not invent a source SHA or bypass the clean-source check.

Offline/local Git transport must also preserve tracked executable modes. The canonical
Linux launcher and its shell entrypoints are committed as executable files, so a
verified Git bundle/clone reproduces both source identity and executable bits. Do not
replace the formal server source cut with a filesystem copy that silently strips
Git mode metadata.

### 3. Verify Docker and environment-profile authority

From the repository root:

~~~bash
./deploy/noetrium infra doctor
./deploy/noetrium infra env list
./deploy/noetrium infra env show minecraft
./deploy/noetrium infra env validate
~~~

The profile authority is <code>deploy/environments/catalog.json</code>. Current reusable categories are text_world, web, minecraft, gui, embodied and software. The central builder does not hard-code that set.
### 4. Build or reuse exact environment images

Build every active default profile:

~~~bash
./deploy/noetrium infra build
~~~

Or one profile:

~~~bash
./deploy/noetrium infra env build --profiles minecraft
~~~

The build path is:

~~~text
exact clean source cut
  -> qualified Noetrium distribution/wheel
  -> evidence-bound base image
  -> exact upstream runtime image identities
  -> environment profile image
  -> image-local doctor
  -> provenance/build receipt
~~~

The base image is built from one formally prepared evidence-bound wheel, not from a mutable source-tree copy. Exact source, wheel and runtime identities are recorded and verified.

Profile revisions are immutable. A draining revision requires explicit recovery intent and a retired revision requires explicit historical-recovery intent:

~~~bash
./deploy/noetrium infra env build --profiles <profile> --allow-draining
./deploy/noetrium infra env build --profiles <profile> --allow-retired
~~~

### 5. Environment isolation

The invariant is:

> **Share immutable content; isolate all mutable execution state.**

Shared examples include image layers, content-addressed assets, dependency caches and immutable runtime artifacts.

Private per-execution state includes workspace, tmp, runtime state, secrets, process/network namespace, ports, browser profile, world state and application state.

A warm instance returns to a pool only after an explicit cleanliness proof. Otherwise it is destroyed.

The Minecraft profile provides Java 21, Node 22 and the lockfile-pinned Mineflayer runtime. Benchmark servers, worlds, tasks, methods, models and checkpoints stay downstream.

Minecraft actions are declared once as typed NoetriumUnit capabilities. The same catalog defines execution validation, agent-visible semantics, permitted argument ranges and enumerations, and physical effect classes. An agent can inspect one authorized action without touching world state by invoking `describe_action` with `{"action_type":"equip_item"}` as the action arguments. Its `ACTION_DESCRIBED` outcome returns the public canonical parameter JSON Schema, purpose, semantic domains and applicability, but never reveals forbidden actions, hidden benchmark rules or an inferred inventory. It is a `PURE` observation: documentation is declared capability truth, not evidence that a block or item exists. The platform's single Method Model Request Factory derives per-action constrained generation schemas and compact Agent-visible catalogs from this same authorized contract; downstream Methods need not compile tool grammars, inspect Provider internals or implement Minecraft prompt renderers. The scientific planner and memory algorithm remain the downstream paper's responsibility.

### 5.1. Universal Agent Context Engine and Method memory

The common Method Model Request Factory composes context without hardcoded world-state, inventory, GUI-widget or robotics-joint ontologies. Its seven source-separated projections cover the goal, provider-authorized observations, capability contracts, execution history, method-owned retrieved memory, method policy and output contract. Domain Providers supply public Agent Context facets only after the single visibility cut. GUI and embodied Providers use the same compiler with their own typed values.

Declared, authorized, observed and evidenced environment truth stay separate. Recalled memories are marked recalled_not_live_observation: historical hypotheses never become proof of the current world. An indeterminate physical effect invalidates freshness claims without inventing results. Unit Methods freely define memory storage, retrieval, update, forgetting, restructuring and evolution, without a platform-default memory algorithm contaminating paper baselines.

The authorized Capability descriptor is the one source of action semantics. The Model Request Factory derives a compact tool catalog and strict per-action JSON Schema together, rejecting unauthorized actions and conflicting schemas. This applies to Minecraft, GUI, browser, robotics and multimodal environments; physical effects stay with the Provider.

### 6. Plan the repository fleet before execution

Static planning starts no work:

~~~bash
./deploy/noetrium infra plan
~~~

The repository-fleet planner discovers the platform's reference/validation reproductions, compiles each research.program Unit and builds one top-level recursive research.portfolio Unit plus disposable execution projection without starting work. It reports compile failures, unresolved external-asset requirements, reproduction-closure gaps, materialization readiness, Study requirements and graph identities. Concrete benchmark/method semantics for an independent downstream paper remain in that downstream repository.

Having a directory below <code>research/reproductions/</code> does not by itself make a paper runnable. Execution requires exact closure.

### 7. Materialize owner-authority prerequisites

Emit the machine-readable prerequisite manifest:

~~~bash
./deploy/noetrium infra requirements
~~~

The canonical repository path uses Noetrium's built-in owner-authority materialization. `preflight` and `run` derive binding requirements from frozen Programs/Studies and ask the actual Model, Environment, Participant, Resource, Artifact/Benchmark and Trial owners to close them. The materializer may compose authority; it may not invent authority.

For Model requirements, the current path is platform-owned end to end: resolve or materialize the declared model asset, freeze its content identity, resolve an engine OCI image and freeze its immutable image identity, materialize one `ModelStackSpec`, obtain compute/endpoint/container admission, start the replica through the shared service/container lifecycle, perform measured qualification plus requirement-aware runtime canaries, and publish the single current qualified-model closure. Downstream code does not select Docker images, GPU ids, ports, service processes or qualification files.

Machine-local or external facts that cannot be inferred uniquely remain explicit repository-operator inputs, for example an externally stored dataset/benchmark asset cut or other external materialization. This operator input closes an external asset requirement; it does not move the benchmark's scientific semantics into Noetrium:

~~~bash
export NOETRIUM_CONTROL_INPUT_ROOT=/data/noetrium-authority-assets
./deploy/noetrium infra plan --authority-audit \
  --authority-input benchmark.gsm8k.test_jsonl=/data/noetrium-authority-assets/gsm8k/test.jsonl
~~~

When an authority input refers to host data that the Docker control plane must read, `NOETRIUM_CONTROL_INPUT_ROOT` is the allowed read-only host root. Benchmark/materialization code must verify source revision, content digest and task-cut identity; a path string is not authority proof. Stateful audit/runtime output remains under `$NOETRIUM_DEPLOYMENT_STATE_ROOT`, never inside a read-only source checkout.

The automatic materializer never silently substitutes a model, environment, GPU, endpoint, verifier or external asset. A lane whose required owner authority cannot prove exact closure remains `BLOCKED`; unrelated authority-closed lanes may still run. Downstream-owned Method and Benchmark implementations are already part of the frozen scientific definition and are not selected from an upstream paper catalog.

The launcher still exposes `NOETRIUM_FLEET_AUTHORITY_MATERIALIZER=module:factory` as an advanced repository-operator hook in this source cut. It is **not** the canonical downstream project API and must not encode paper semantics or create shadow Model, Environment, Resource, Execution, Effect or Journal authorities. New platform composition should prefer the built-in owner path.

### 8. Preflight the complete execution closure

~~~bash
./deploy/noetrium research preflight
~~~

Preflight resolves exact authority closure, filters the authority-closed runnable subgraph, and performs admission without creating an execution cut or starting tasks. Source/materialization blockers and owner-authority gaps are reported per lane and do not abort unrelated lanes.

If no lane currently closes, preflight returns a structured <code>no-runnable-lanes</code> report instead of asking the operator to wire providers manually. Do not bypass blocked lanes with a paper-local runner.

### 9. Execute

~~~bash
./deploy/noetrium run
~~~

Unless <code>NOETRIUM_SKIP_ENVIRONMENT_BUILD=1</code> is intentionally set, the launcher builds/reuses active environment profiles first.

The real execution path is:

~~~text
./deploy/noetrium run
  -> host Docker/Compose doctor
  -> containerized control-plane bootstrap
  -> exact environment image build/reuse
  -> reproduction discovery
  -> recursive NoetriumUnit validation + execution projection
  -> authority materialization
  -> whole-graph admission
  -> ManagedResearchRuntime
  -> ResearchGraphScheduler
  -> experiment/model/environment/provider execution
  -> Machine / Operation / Effect / Evidence authorities
  -> durable result/evidence closure
~~~

### 10. Large-scale scheduling and shared-host behavior

ResearchGraph scheduling is dependency-aware:

~~~text
pending
  -> dependency frontier
  -> ready set
  -> concurrent submission
  -> terminal result
  -> downstream unlock or BLOCKED propagation
~~~

Repository execution is also lane-fault-isolated before graph admission. Benchmark
or reproduction-closure failure in one paper does not abort unrelated papers.
Noetrium independently materializes every exact lane, compiles the closed subset
into the runnable research.portfolio Unit projection, and retains content-addressed BLOCKED records
for the rest. A lane with an externally selected benchmark split must match that
split exactly; a Study that owns its split internally may materialize its own
canonical split without inventing an external selection.

Bound reproduction ResearchProgram identities are content-addressed by the exact
execution-binding digest rather than by embedding free-form binding labels. This
keeps program IDs valid, deterministic and collision-resistant across arbitrary
paper-owned binding names.

Durable scheduling adds attempt identities, leases, retry timing, per-node control and reconciliation-required states.

ResearchExecutionPool separates control, fleet/top-level dispatch, orchestration, experiment, Machine, model-I/O and capability-I/O concerns. Parent domains that synchronously wait on child work do not share the same blocking worker pool, preventing nested admission deadlock. Workload domains share one CPU worker provider and one residual-capacity reservation ledger so separate gates cannot spend the same RAM/PID/FD/storage headroom concurrently.

Execution tenants propagate from the project/portfolio root through Experiment, Trial, Workload, child-Machine, environment-capability and model-request execution. Fair admission considers current tenant and group in-flight share before historical grant order. This prevents a paper with thousands of ready episodes from starving a paper with a small frontier, while a single active paper can still consume otherwise idle capacity.

Model requests add an engine-pressure feedback loop on top of the same fair admission. Qualified deployments bind a hard safe concurrency ceiling and a preferred operating point derived from measured performance. The runtime window adapts within that envelope using completion behavior, rate-limit responses and normalized engine pressure. For vLLM, the pressure projection includes running/waiting requests, KV-cache usage, preemption and prefix-cache counters. Prefix affinity and pooled HTTP transport preserve locality and connection reuse; vLLM itself remains responsible for continuous token batching.

Lease heartbeats run through the independent control domain. Compute/GPU, endpoint, EnvironmentInstance and Docker-container fencing can therefore continue while workloads are quiescing.

On a shared host, use currently idle residual capacity while respecting pre-existing external workloads. Pressure blocks new admission; it does not normally kill already admitted Noetrium work.

### 11. GPU, endpoint and Docker ownership

Papers declare requirements; Platform resource authorities select physical identities.

Endpoint lifecycle is:

~~~text
candidate
  -> OS binding validation
  -> atomic reservation
  -> lease/fencing generation
  -> exact binding proof
  -> heartbeat
  -> physical convergence
  -> release/reuse
~~~

Compute/GPU ownership follows the same authority principle.

Containerized model services use the shared exact service lifecycle and the same Docker-container lease authority used by the physical resource layer. Model authority owns model identity, stack, deployment and qualification semantics; service authority owns start/readiness/stop/reconciliation; container authority owns the physical Docker generation, fencing and recovery. Model code does not own a private Docker lifecycle.

Docker-managed containers are generation-bound and reconciled against physical daemon state. A stopped exact-generation container may be parked and resumed through the container authority, but mutable scientific state is never inferred from container survival. Container convergence must be proven before dependent environment, endpoint or compute ownership is released.
### 12. Shutdown, crash and restart semantics

Normal ManagedResearchRuntime shutdown detaches the project consumer without treating reusable physical runtime as project-owned garbage:

~~~text
quiesce project/background submission
  -> quiesce experiment, capability and model I/O for this consumer
  -> flush durable Machine / effect / evidence state
  -> release project-scoped guards and heartbeat ownership
  -> detach the Runtime Fabric consumer lease
  -> close project-local observability and execution pools
  -> release managed-runtime interprocess lock LAST
~~~

Exact model services, qualified deployments, reusable environment realizations and their physical containers may remain warm when their durable owner state is still valid. Terminal retirement and pressure reclamation are separate owner-authority operations: they first prove exclusive Runtime Fabric consumer conditions, stop or retire the physical generation, and only then release dependent endpoint/compute ownership. A normal project close does not masquerade as terminal physical GC.

If a retirement or reconciliation stage cannot prove convergence, later dependent resources remain fenced. `EndpointPhysicalConvergencePending` and equivalent physical-pending states therefore block unsafe lower-resource release, but the long-lived resource controller retries them rather than failing the whole controller task.

After SIGKILL, SSH loss or a crashed prior controller, the next exclusive managed runtime performs startup reconciliation before admitting new work. A stopped durable realization is adopted only after its exact generation and current physical placement are re-proved; lost capacity, stale generations and expired ownership are fenced and replanned through the canonical resource authorities rather than revived blindly.

Machine Journals, checkpoints, artifacts, evidence, immutable assets and recovery-required workspaces are durable recovery carriers, not ephemeral leaks. They follow retention/GC policy rather than crash cleanup.

### 13. Bootstrap-container crash handling

<code>deploy/build-environments.sh</code> runs control-plane Python inside a bootstrap container connected to the active host Docker daemon.

Bootstrap containers carry exact host owner identity: PID, boot id and process-start generation. Normal EXIT/HUP/INT/TERM performs cleanup. A later launcher removes only orphan bootstrap containers whose exact owner generation is proven gone. Docker <code>--rm</code> is treated as an optimization, not proof of physical convergence.

### 14. Upstream versus downstream

Keep reusable execution machinery upstream: Research execution/Machine substrate, resource admission and leases, process/service/container lifecycle, generic environment profiles/providers, model-serving mechanics, artifacts/evidence/data authorities, generic experiment/recovery mechanisms and deployment tooling.

Keep scientific novelty downstream: concrete MethodPrograms, comparison methods, memory semantics, prompts/policies, benchmark builders and task assets, task success criteria, paper worlds/assets, paper model selection, experiment hypotheses/matrices and claim interpretation.

Move a mechanism upstream only when it is genuinely reusable across papers and can be expressed without importing one paper's scientific claim into Platform authority.

### 15. Before adding a Runner, Manager, Controller or adapter

Check <code>noetrium</code>, the system registry and generated architecture map first.

If the need is paper-variable, prefer Program/sub-IR/policy/handler. If it is physical/provider mechanics, extend the owning typed provider. If an authority already exists, reuse it.

Do not add a second durable history, scheduler, lease registry, checkpoint authority, Docker owner or resource allocator.

### 16. Current execution model

The canonical source path uses one executable ResearchProgram/Machine model across Method, Runtime, Participant, workload, optimization and other programmable research domains.

| Area | Canonical behavior |
| --- | --- |
| Unit/Event composition | recursive immutable semantics, content-addressed revisions, causal execution events and lazy physical-plane materialization |
| Scientific execution | ResearchProgram -> ProgrammableMachineInterpreter -> MachineExecutor -> Machine Journal |
| Method execution | typed Method semantics lower deterministically to ResearchProgram(kind=METHOD); Method facades project typed results but own no second transition engine |
| Participant execution | frozen participant schedules compile to parent ResearchPrograms; roles execute as child Machines with exact child-cut links |
| Workload execution | dependency DAGs compile to journal-backed Run ResearchPrograms and execute through a bounded completion-driven frontier with immediate dependent refill; no process-local scheduler owns recovery truth |
| Model runtime | declared model requirements resolve to exact assets and an immutable ModelStack; compute/endpoint/container placement, replica startup, measured safe/preferred concurrency qualification, topology-stable qualified refresh, circuit-breaker recovery, prefix-aware pooled transport, adaptive admission from latency/rate-limit/vLLM pressure, qualified closure and durable request/effect evidence are platform-owned |
| Capability/effect runtime | one capability/effect intent/receipt/reconciliation path with explicit certainty |
| Environment runtime | exact environment/session identity, assignment-scoped lifetime, atomic reusable-instance provisioning, catalog/lease admission fencing, deterministic seed derivation when required, and owner-managed provider mechanics |
| Budget/replay | one durable assignment-lifetime authority for scientific steps, time, calls, messages, tokens, cost and replay proof; physical admission remains platform-owned |
| Artifact/evidence/data | canonical owner authorities; no run-local identity shadow store |
| Resource/runtime lifecycle | shared-host admission, compute/GPU allocation, endpoints, Docker/process/service generations, leases, heartbeats, cleanup and abandoned-owner recovery |

The normal project path is:

~~~python
from noetrium import run

report = run(".")
~~~

Downstream code should not manually construct model, environment, resource, Docker, Machine or evidence authorities. Frozen requirements resolve through their canonical owners. If an exact binding or proof cannot be established, execution fails closed.
