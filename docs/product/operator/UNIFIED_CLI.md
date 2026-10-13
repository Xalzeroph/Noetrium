# Unified Noetrium CLI

Noetrium exposes one operator command tree: `noetrium`. The repository launcher `./deploy/noetrium` enters the same hierarchy for Docker-first/server operation.

The CLI is an operator surface over the platform authorities; it is not a second scheduler, journal, resource ledger, or scientific runtime.

## First setup

Register one project and validate the workspace without starting work:

```bash
noetrium workspace init --project /path/to/project
noetrium workspace doctor
noetrium project list
```

A checkout may infer its own platform root. Workspace discovery walks the current directory and its parents; use `--workspace FILE` or `NOETRIUM_WORKSPACE_FILE` only when operating outside that tree.

`workspace init`, `workspace show`, `workspace doctor`, and `workspace attach` are configuration/provenance operations. They do not start Docker or research execution.

## Command groups

| Group | Responsibility |
| --- | --- |
| `workspace` | saved project/platform bindings and non-effectful setup checks |
| `project` | register, select, create, sync, doctor, and test research projects |
| `research` | run lifecycle, status, logs, recovery, versions, checkpoints, and provenance |
| `infra` | Docker, environment images, managed resources, planning, and infrastructure checks |
| `diagnose` | evidence, failure, runtime, telemetry, recovery, release, and architecture inspection |
| `dev` | architecture, algorithm, concurrency, performance, repository-boundary, and release operations |
| `guide` | lifecycle guidance that does not execute work |

`noetrium run` is the short form of `noetrium research run`.

Explore the tree with either form:

```bash
noetrium help
noetrium help research
noetrium research --help
noetrium infra --help
```

## Projects and composed project sets

A workspace may register more than one research project:

```bash
noetrium project add paper-a /path/to/paper-a
noetrium project add paper-b /path/to/paper-b
noetrium project use paper-a paper-b
noetrium project list
```

The selected project set is composed through the same portfolio/root-set execution backend. Projects may live in separate repositories or in one shared repository. Source identity is frozen by repository and relative project root; aliases are operator metadata, not scientific identity.

Create and validate a project with:

```bash
noetrium project create my-paper ./my-paper
noetrium project doctor --project ./my-paper
noetrium project test --project ./my-paper
```

## Research lifecycle

Preflight verifies source and authority closure without starting an experiment:

```bash
noetrium research preflight
```

Start or select the active execution:

```bash
noetrium run
noetrium research status
noetrium research logs --lines 100
```

A fresh independent execution is explicit:

```bash
noetrium run --new --name experiment-2
```

Lifecycle operations are explicit and evidence-preserving:

```bash
noetrium research pause
noetrium research drain
noetrium research interrupt
noetrium research resume
noetrium research retry
noetrium research checkpoint
noetrium research reconcile
noetrium research cancel
noetrium research retire
```

`pause` and `drain` are cooperative. `interrupt` can leave reconciliation debt. `resume` continues the same frozen execution against durable state. `retry` reopens eligible failed work through the native recovery authority; it does not require deleting journals or checkpoints. `cancel` and `retire` are terminal lifecycle actions and must satisfy their quiescence requirements.

## Run and version history

History commands are read-only unless their action explicitly creates or selects metadata:

```bash
noetrium research runs list
noetrium research runs show RUN_NAME
noetrium research versions compare LEFT RIGHT
noetrium research checkpoints list --run RUN_NAME
```

A recorded run preserves its original platform/project/environment bindings. Selecting another run changes operator focus; it does not rewrite that run's provenance.

`workspace attach` may bind an existing execution into a workspace without executing or migrating it:

```bash
noetrium workspace attach existing-run \
  --platform-root /path/to/frozen/platform \
  --project /path/to/frozen/project \
  --data-root /path/to/run-state
```

The CLI validates the recorded binding before lifecycle operations. An override cannot silently redirect a run to unrelated state.

## Recovery

Use `research recover` for explicit recovery planning/execution when durable state needs repair or replay policy beyond ordinary resume/retry. Recovery operates against recorded source and run identity and should be preceded by inspection:

```bash
noetrium research status
noetrium diagnose recovery status
noetrium research recover --help
```

Uncertain external effects remain fenced until their effect authority can reconcile them. Recovery must not infer `NO_EFFECT` from a timeout, process loss, or transport failure.

## Infrastructure

Infrastructure commands are under one group:

```bash
noetrium infra doctor
noetrium infra plan
noetrium infra requirements
noetrium infra env list
noetrium infra env validate
noetrium infra docker status
```

The repository launcher provides the same hierarchy for server/Docker-first operation:

```bash
./deploy/noetrium infra doctor
./deploy/noetrium research preflight
./deploy/noetrium run
```

## Diagnostics and development gates

Diagnostics observe platform authorities without becoming them:

```bash
noetrium diagnose evidence --help
noetrium diagnose failure --help
noetrium diagnose runtime --help
noetrium diagnose telemetry --help
noetrium diagnose release --help
```

Development gates live under `dev`:

```bash
noetrium dev architecture gate
noetrium dev algorithm scan
noetrium dev concurrency gate
noetrium dev performance scan
noetrium dev boundary audit .
noetrium dev release status
noetrium dev release prepare --version 1.0.0
noetrium dev release build --version 1.0.0
noetrium dev release verify --version 1.0.0
# One-shot publication after the source commit is clean:
noetrium dev release --version 1.0.0 --publish
```

`dev release` is the canonical maintainer release surface. `prepare` synchronizes and checks generated authorities plus high-confidence secret/machine-path scans; `build` creates the qualified wheel/sdist closure; `verify` rebinds those artifacts to the current source tree; and `publish` fails closed unless Git is clean, then pushes the current branch/tag and creates the GitHub Release. Repository replacement or migration is intentionally outside this reusable command.

For exact options, use `--help` on the installed version rather than copying historical command lines from old runs.
