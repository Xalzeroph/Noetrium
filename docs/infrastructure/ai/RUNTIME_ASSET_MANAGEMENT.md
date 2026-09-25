# Runtime Asset Management

This management plane is for day-to-day server operations. It is intentionally separate from scientific qualification and release freezing.

## Scope

It manages three mutable resource families:

```text
Directory Manager
├─ releases / runtime / state / logs
├─ model artifacts / Python environments
├─ cache / temp / locks
└─ workspaces

Python Environment Manager
├─ venv
├─ conda
├─ mamba
├─ registered external prefixes
├─ tags / direct run / package inventory
└─ centralized pip + conda package caches

Model Management Authorities
├─ Asset Management
│  ├─ local reference/copy/move/symlink
│  ├─ named storage pools
│  └─ pluggable model-source backends
├─ Deployment Management
│  ├─ desired/applied runtime state
│  ├─ tags + selectors
│  └─ start / stop / restart / status / reconcile
├─ Desired-State Controller
│  └─ foreground reconcile loop for tmux/systemd/container hosting
└─ Resource View
   ├─ environment references
   ├─ declared GPU allocations/conflicts
   └─ best-effort live GPU status
```

A research run may later freeze one selected model/environment/runtime binding into the scientific runtime manifest. The management plane itself does not require a qualification certificate before normal operator actions.

## Automatic deployment qualification

Before materializing a serving environment, use the qualification node to
collect the complete capability closure and produce an exact package plan. It
inspects the operating system, kernel, NVIDIA driver/CUDA API, toolkit/NVRTC
libraries, GPU model/memory/compute capability, selected Python bootstrap
support, model `config.json`, and the requested backend package indexes.

```bash
noetrium-manage --config configs/runtime_management.json \
  deployment qualify \
  --model-id MODEL_ID \
  --model-path /models/MODEL_ID \
  --python /envs/serving/bin/python \
  --backend backend-a \
  --backend backend-b \
  --tensor-parallel 4
```

The selected Python path is intentionally not symlink-resolved: a virtual
environment's `bin/python` may point to the system interpreter while its
`site-packages` contains the serving stack. The resulting plan records exact
package versions and index URLs, rejects candidates whose observed
architecture-specific extensions do not cover the host, and leaves package
installation and live readiness to the existing environment/deployment
authorities. A selected plan is not a runtime or scientific qualification
certificate; `pip check`, imports, extension loading and endpoint qualification
must still produce evidence.

## Explicit directory layout

Use `configs/runtime_management.example.json` as a starting point. Every cross-authority directory is explicit. The manager does not derive state/log/model/env roots from another store path.

Initialize and inspect:

```bash
noetrium-manage --config configs/runtime_management.json dirs init
noetrium-manage --config configs/runtime_management.json dirs show
noetrium-manage --config configs/runtime_management.json dirs stats model_artifacts
noetrium-manage --config configs/runtime_management.json summary
```

`summary` is intentionally lightweight: it reports top-level entry counts and filesystem capacity without recursively walking every model/environment/log file. Deep recursive accounting happens only in explicit `dirs stats`, `dirs entries`, or `model stats` commands.

Workspaces:

```bash
noetrium-manage --config configs/runtime_management.json \
  dirs workspace-create study-run-001 --category study --owner downstream-project
noetrium-manage --config configs/runtime_management.json \
  dirs workspace-list --category study
```

Find the largest top-level entries without changing anything:

```bash
noetrium-manage --config configs/runtime_management.json dirs entries model_artifacts --limit 20
noetrium-manage --config configs/runtime_management.json dirs entries logs --limit 20
```

Only cache/temp support automatic `dirs clean`; scientific state/release/model directories are never accepted by that command.

## Python environments

Create a regular venv using a selected base interpreter:

```bash
noetrium-manage --config configs/runtime_management.json \
  env create serving-main --backend venv --python /usr/bin/python3.11 --tag serving --tag gpu
```

Environment tags are management metadata and may be used to group large server inventories. Pip downloads use the explicit platform cache directory; conda/mamba package caches are also placed under the configured cache authority rather than implicitly spreading into the operator home directory.

Create conda/mamba prefixes:

```bash
noetrium-manage --config configs/runtime_management.json \
  env create serving-conda --backend conda --python-version 3.11

noetrium-manage --config configs/runtime_management.json \
  env create serving-mamba --backend mamba --python-version 3.11
```

Register an existing prefix without copying it. Registered prefixes are marked `external`; removing them from the manager removes only registry metadata. Environments created by the manager are marked `managed` and their directory is owned by the manager. Environment assets live under `python_environments`, while the single management registry lives under `state/python-environments`; there is no second `_registered` namespace.

```bash
noetrium-manage --config configs/runtime_management.json \
  env register shared-serving /opt/venvs/serving --backend venv
```

Install requirements, install individual packages, inspect packages, or execute directly inside a managed environment:

```bash
noetrium-manage --config configs/runtime_management.json \
  env install serving-main requirements-serving.txt
noetrium-manage --config configs/runtime_management.json \
  env pip-install serving-main backend-package extension-package
noetrium-manage --config configs/runtime_management.json \
  env packages serving-main
noetrium-manage --config configs/runtime_management.json \
  env run serving-main -m pip check
noetrium-manage --config configs/runtime_management.json \
  env command serving-main -m python_module
```

## Model assets

Reference an existing weights directory:

```bash
noetrium-manage --config configs/runtime_management.json \
  model add model-local /data/models/MODEL --family example-family
```

Large model assets support four explicit management modes:

```text
reference  keep the original path in place
copy       copy into the platform model-artifacts directory
move       move into the platform model-artifacts directory
symlink    create a platform-owned symlink to the original path
```

Examples:

```bash
noetrium-manage --config configs/runtime_management.json \
  model add model-copy /data/models/MODEL --mode copy --family example-family
noetrium-manage --config configs/runtime_management.json \
  model add model-link /data/models/MODEL --mode symlink --family example-family
```

For multi-hundred-GB weights, `reference` and `symlink` avoid unnecessary data movement. `copy` and `move` are available when the platform should own the files.

Managed assets can be placed on named storage pools. `model_artifacts` is the `default` pool; additional NVMe/archive/NAS roots are configured explicitly under `model_storage_pools` and never inferred from another path.

```bash
noetrium-manage --config configs/runtime_management.json model pools
noetrium-manage --config configs/runtime_management.json \
  model add model-fast /data/staging/MODEL --mode move --pool nvme --tag online
noetrium-manage --config configs/runtime_management.json \
  model fetch model-archive provider/MODEL --backend huggingface --pool archive
```

Inspect disk size and deployment references only when needed; these recursive scans are deliberately not run by every normal status call:

```bash
noetrium-manage --config configs/runtime_management.json model inspect model-local
noetrium-manage --config configs/runtime_management.json model stats model-local
noetrium-manage --config configs/runtime_management.json model refs model-local
```

The registry is operational metadata. It is not a qualification certificate.

Model acquisition is a separate source backend. The default local composition provides a Hugging Face CLI backend; a failed partial download remains unregistered and may be resumed with the same command.

```bash
noetrium-manage --config configs/runtime_management.json model sources
noetrium-manage --config configs/runtime_management.json \
  model fetch model-fetched provider/MODEL --backend huggingface --revision main --family example-family
```

`model fetch` resumes an existing unregistered target directory by default. Use `--no-resume` when an existing partial directory should be treated as an error instead. The CLI executable is configured under `model_sources.huggingface_cli`; it is not hard-coded into scientific runtime logic.

For large resumable acquisitions, the source contract can expose the
Hugging Face worker count without changing model identity:

```bash
noetrium-manage --config configs/runtime_management.json \
  model fetch model-fetched provider/MODEL --backend huggingface --revision main \
  --max-workers 24
```

The worker count affects acquisition throughput only. It does not bypass the
asset registry, change the revision, or make an incomplete directory usable.

### Environment identity

Every newly created or registered Python environment freezes a
`specification_digest` over its logical id, scope, backend, base interpreter,
requested Python version, description and normalized tags. The registry also
uses the materialized root/interpreter paths and that specification digest to
derive the instance identity. A registry record without the digest is
rejected; path existence alone is not sufficient evidence that an environment
is the one requested by a run.

Registry records that do not contain the current immutable
`specification_digest` are invalid and are rejected. No migration path is
provided by the runtime authority. Operators must create or explicitly register
a current environment with complete identity inputs; the platform never infers
or upgrades an incomplete historical identity.

Environment inventory is deliberately bounded: the manager enumerates only
the JSON records under `state/python-environments`. It never recursively
searches model pools, caches, releases or logs to discover an environment.
This keeps inventory latency and transport lifetime independent of model size
and makes interrupted audits recoverable through the server operation ledger.

The venv and conda providers select the interpreter path according to the
controller OS (`bin/python` on Linux and `Scripts/python.exe`/`python.exe` on
Windows). The Python registry identity and the server package-lock identity
are separate authorities: the registry identifies the logical environment
instance, while a server profile identifies the exact runtime package set used
by remote operations. Both are required evidence before a scientific run is
admitted.

## Deployments

A deployment is generic. It freezes neither a specific serving engine nor a fixed CLI grammar in the manager. `executable` and `argv` are operator-owned launch data.

Placeholders currently supported in argv:

```text
{python}
{model_path}
{model_id}
{deployment_id}
```

`{python}` is resolved through the selected Python environment. GPU allocation becomes `CUDA_VISIBLE_DEVICES` in the child environment. A deployment can also provide arbitrary environment variables and an optional HTTP readiness URL.

Register a deployment:

```bash
noetrium-manage --config configs/runtime_management.json \
  deployment put-json configs/model_deployment.example.json
```

Operate it:

```bash
noetrium-manage --config configs/runtime_management.json deployment start model-deployment-0
noetrium-manage --config configs/runtime_management.json deployment status model-deployment-0
noetrium-manage --config configs/runtime_management.json deployment restart model-deployment-0
noetrium-manage --config configs/runtime_management.json deployment stop model-deployment-0
```

GPU management exposes both desired assignments and a best-effort live NVIDIA view. Live `nvidia-smi` data is observational only and never blocks start/reconcile:

```bash
noetrium-manage --config configs/runtime_management.json deployment gpu
noetrium-manage --config configs/runtime_management.json deployment gpu-conflicts
noetrium-manage --config configs/runtime_management.json deployment gpu-runtime
```

Fleet operations are isolated per deployment, so one missing model/environment is reported as `MISSING` without aborting management of the remaining fleet:

```bash
noetrium-manage --config configs/runtime_management.json deployment status-all
noetrium-manage --config configs/runtime_management.json deployment reconcile
noetrium-manage --config configs/runtime_management.json deployment start-all
noetrium-manage --config configs/runtime_management.json deployment stop-all
```

## Tags, selectors, and desired-state controller

Deployments can carry tags and can be selected by tag/model/engine/Python environment. This is intended for fleets such as `online`, `batch`, `batch`, or `gpu-a100`.

```bash
noetrium-manage --config configs/runtime_management.json deployment list --tag online
noetrium-manage --config configs/runtime_management.json deployment desire model-deployment-0 running
noetrium-manage --config configs/runtime_management.json deployment desire-all running --tag online
noetrium-manage --config configs/runtime_management.json deployment desire-all stopped --env old-serving-env
```

`desire` and `desire-all` change only management desired state. They do **not** immediately issue process effects. The reconcile controller converges actual runtime state to those declarations.

The controller itself is a foreground, backend-neutral process:

```bash
noetrium-manage --config configs/runtime_management.json controller run --interval-seconds 10
noetrium-manage --config configs/runtime_management.json controller status
```

On a server, host the foreground command in the existing persistent-session layer (tmux by default), systemd, a container supervisor, or another scheduler. Model management does not import tmux-specific code. Controller status persists the PID, heartbeat, cycle count, and most recent deployment results for operator inspection.

## Desired versus applied configuration

Deployment configuration is mutable. The manager separately retains the last applied configuration.

```text
operator edits desired deployment
        ↓
running old deployment remains identifiable
        ↓
status = UPDATE_PENDING
        ↓
reconcile
        ↓
stop old applied contract
        ↓
start new desired contract
        ↓
applied := desired
```

This is management state, not scientific state. It exists so changing ports, GPU assignment, serving engines, Python environments, or command arguments does not orphan the previous process.

## tmux relationship

`tmux` remains the default persistence mechanism for the outer controller/operator session, but the desired-state controller is intentionally a normal foreground process. The same command can therefore be hosted by systemd, a container supervisor, or a remote scheduler. Model truth still comes from Service OS process state and model-management desired/applied state. A tmux session is never interpreted as model readiness.


## Mutable registries versus applied runtime snapshots

Model management now keeps **three separate durable authorities** rather than one combined registry:

```text
model asset registry        -> where managed/referenced weights are
desired deployment registry -> what the operator wants to run
applied deployment store    -> exact launch snapshot of what is/was applied
```

Deleting or editing desired configuration therefore cannot silently erase the exact applied runtime snapshot needed to stop or inspect a running process.

Per-deployment lifecycle (`start/stop/restart/status/remove`) is also separate from fleet policy (`status-all/reconcile/start-all/stop-all`). The foreground desired-state controller consumes only the fleet authority.


Model and Python-environment registries are operator-managed and may change while a model is running. The running instance is therefore tracked by a separate applied runtime snapshot containing its exact service launch contract and child environment.

```text
mutable model/env registry
        ↓
new desired materialization
        ↓
UPDATE_PENDING

old applied runtime snapshot
        ↓
status / exact stop remain available
        ↓
reconcile starts the new desired configuration
```

This makes routine path changes, environment replacement, GPU reassignment, and serving-engine upgrades manageable without turning the mutable registry into a scientific freeze authority.
