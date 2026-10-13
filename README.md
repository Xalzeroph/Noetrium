<!-- readme-nav:start -->
<p align="center">
  <strong>English</strong> ·
  <a href="README.zh-CN.md">简体中文</a>
</p>
<!-- readme-nav:end -->

<!-- readme-locale:en -->
<!-- readme-source-sha256:18bbf2f6259effae6edeb5633d48407f91dfc8ca348779f54a3e03a4f3615e9c -->

<h1 align="center">Noetrium</h1>

<p align="center">
  <strong>Reproducible research infrastructure for AI agents.</strong><br>
  Compose experiments at the top; preserve identity, execution truth, recovery, resources, effects, artifacts, and evidence underneath.
</p>

<p align="center">
  <a href="https://github.com/Xalzeroph/Noetrium/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/Xalzeroph/Noetrium/ci.yml?branch=main&label=CI"></a>
  <a href="pyproject.toml"><img alt="Version 1.0.0" src="https://img.shields.io/badge/version-1.0.0-blue"></a>
  <a href="https://www.python.org/"><img alt="Python >=3.12" src="https://img.shields.io/badge/Python-%3E%3D3.12-3776AB?logo=python&logoColor=white"></a>
  <a href="LICENSE"><img alt="Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-green"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> ·
  <a href="docs/INDEX.md">Documentation</a> ·
  <a href="docs/architecture/SYSTEM_ARCHITECTURE.md">Architecture</a> ·
  <a href="docs/product/operator/UNIFIED_CLI.md">CLI</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

<!-- readme-section:overview -->
## Overview

Noetrium is an execution substrate for serious AI-agent research. It is designed for projects that must coordinate models, environments, methods, participants, trials, resources, recovery, and evidence without letting orchestration details become scientific truth.

The public Python surface is intentionally small: `NoetriumUnit` describes immutable research semantics and `run` executes a root through the platform runtime. The internal system is larger because it owns the hard parts that ordinary experiment scripts usually leave implicit: exact identity, durable transitions, bounded effects, resource admission, recovery, provenance, and release evidence.

Noetrium is not a replacement for an agent framework. Agent loops, planners, memories, benchmark logic, prompts, and scientific hypotheses remain project-owned. Noetrium provides the infrastructure around them so that a run can be attributed, inspected, interrupted, resumed, verified, and reproduced against an exact source and binding cut.

<!-- readme-section:why -->
## Why Noetrium?

Long-running agent experiments fail in ways that are easy to hide and difficult to reproduce: a process restarts after an uncertain external action, two schedulers disagree about progress, a model endpoint silently changes, a checkpoint is treated as stronger than the execution history that produced it, or a successful result cannot be tied back to the exact code and resource realization that generated it.

Noetrium addresses those failure modes by making ownership explicit:

- one accepted execution path for scientific state transitions;
- one owner for every durable truth domain;
- immutable research definitions and exact binding identities;
- explicit external-effect certainty and reconciliation;
- crash-durable recovery tied to accepted execution cuts;
- resource, endpoint, process, service, and container ownership with leases and fencing;
- artifacts, measurements, and evidence bound to the run that produced them;
- generated governance checks that reject duplicate authorities and shadow paths.

The result is a platform for research systems, not another convenience wrapper around model calls.

<!-- readme-section:capabilities -->
## Core capabilities

- **Minimal public API.** Downstream Python imports only `NoetriumUnit` and `run` from `noetrium`.
- **Content-addressed research composition.** Programs, studies, methods, benchmarks, metrics, and nested portfolios are immutable semantic values with exact identity.
- **Single execution kernel.** Programmable research domains converge on one journal-backed Machine execution model instead of creating independent runners and checkpoint engines.
- **Typed model and environment boundaries.** Scientific requirements are separated from provider realization, placement, ports, containers, and host lifecycle.
- **Durable recovery.** Recovery is bound to accepted Machine cuts and exact program/binding identity; checkpoints accelerate restore but do not become a second history.
- **Effect certainty.** External mutations use intent, receipt, certainty, and reconciliation semantics. An unknown outcome stays unknown until proven otherwise.
- **Resource ownership.** Compute, GPU, endpoints, processes, services, containers, and reusable environment instances are admitted through owner authorities with leases, generations, and fencing.
- **Concurrent execution without semantic shortcuts.** Dependency-aware scheduling, hierarchical fairness, single-flight construction, shared model serving, and reusable immutable realizations improve throughput without weakening run identity.
- **Evidence-first experiments.** Measurements, artifacts, provenance, checkpoints, and publication evidence are tied to immutable source and execution identities.
- **One operator CLI.** Workspace setup, research lifecycle, infrastructure, diagnostics, and development gates live under one `noetrium` command hierarchy.

For the detailed execution model, read [System Architecture](docs/architecture/SYSTEM_ARCHITECTURE.md) and [Runtime and Deployment](docs/architecture/RUNTIME_AND_DEPLOYMENT.md).

<!-- readme-section:quick-start -->
<a id="quick-start"></a>
## Quick start

Noetrium 1.0 targets Linux/amd64 and uses Docker as the canonical production runtime. From a checkout on a Linux Docker host:

```bash
./deploy/noetrium infra doctor
./deploy/noetrium workspace init --project /path/to/project
./deploy/noetrium research preflight
./deploy/noetrium run
```

The qualified wheel is an internal build/input artifact for the Docker image and an SDK/development surface; it is not the production runtime authority. The complete public Python API available inside the qualified runtime is:

```python
from noetrium import NoetriumUnit, run

root = NoetriumUnit.make_structure(
    "paper",
    traits=("research.portfolio",),
)

report = run(root)
```

To start from a project directory:

```bash
noetrium project create my-paper ./my-paper
cd ./my-paper
noetrium project doctor --project .
noetrium project test --project .
noetrium workspace init --project .
noetrium run
noetrium research status
```

A filesystem project and an in-memory `NoetriumUnit` root enter the same execution architecture. The project layer provides source discovery and operator ergonomics; it does not create a second scientific runtime.

<!-- readme-section:architecture -->
## Architecture

Noetrium separates immutable research meaning from mutable execution authority.

```text
NoetriumUnit research root
        |
        v
validation + immutable binding freeze
        |
        v
ResearchProgram / Machine interpretation
        |
        v
MachineExecutor -> durable Machine Journal
        |
        +--> effect authority -> external providers
        +--> resource/runtime authorities -> physical realization
        +--> artifact/data/evidence authorities -> durable research facts
        +--> observability -> disposable projections
```

The architecture follows a few strict rules: scientific semantics may be modular, but accepted execution has one path; providers perform effects but do not own scientific truth; caches and telemetry are projections, not authorities; and performance optimizations may reuse immutable realization but must isolate mutable scientific state.

The repository implementation is organized as a modular monolith around those ownership boundaries. The public `noetrium` package is deliberately thin; internal subsystems live under `noetrium_platform` and may evolve behind the stable public surface.

Detailed documents:

- [System Architecture](docs/architecture/SYSTEM_ARCHITECTURE.md) — Unit/Event model, Machine execution, authority boundaries, bindings, evidence, recovery, scheduling, and extension rules.
- [Runtime and Deployment](docs/architecture/RUNTIME_AND_DEPLOYMENT.md) — Docker-first deployment, model serving, environment lifecycle, resource ownership, shutdown, crash recovery, and large-scale scheduling.
- [Documentation Index](docs/INDEX.md) — all maintained v1.0 documentation.

<!-- readme-section:cli -->
## Unified CLI

Noetrium has one command tree:

```bash
noetrium help
noetrium workspace doctor
noetrium project list
noetrium research preflight
noetrium research status
noetrium diagnose runtime status
noetrium infra doctor
noetrium dev architecture gate
noetrium dev release status
```

`noetrium run` is the short form of `noetrium research run`. Existing runs are inspected or resumed explicitly; a fresh independent execution is created with `--new`. Lifecycle commands never require deleting journals or checkpoints to make progress.

See the [Unified CLI Guide](docs/product/operator/UNIFIED_CLI.md) for workspace binding, multi-project execution, run history, recovery, diagnostics, and development commands.

<!-- readme-section:deployment -->
## Deployment

For Linux servers, the canonical operational entry is the repository launcher, which enters the same CLI hierarchy inside the deployment environment:

```bash
./deploy/noetrium infra doctor
./deploy/noetrium workspace init --project /path/to/project
./deploy/noetrium research preflight
./deploy/noetrium run
```

Noetrium supports Docker-first execution, reusable content-addressed environment images, managed model runtimes, explicit host resource admission, and crash reconciliation. GPU placement, endpoint allocation, service/container lifecycle, and model-serving concurrency are platform-owned physical decisions rather than project-level scientific configuration.

See [Runtime and Deployment](docs/architecture/RUNTIME_AND_DEPLOYMENT.md) before operating shared hosts or long-running experiments.

<!-- readme-section:reliability -->
## Reliability and reproducibility

Noetrium is fail-closed where uncertainty would otherwise become false scientific confidence.

- A timeout after a mutating effect does not prove the effect did not happen.
- A checkpoint does not outrank the durable execution history that authorizes it.
- A recovered run must match the recorded program and binding identity.
- Resource reuse requires exact identity and valid ownership/fencing state.
- Model or environment substitution is not silently treated as equivalent.
- Release evidence is valid only for the exact source cut that produced it.

Repository verification combines unit/integration tests with architecture, public-contract, governance, and release-distribution gates. The exact release process is documented in [Release System](docs/governance/RELEASE_SYSTEM.md) and [Distribution Qualification](docs/release/DISTRIBUTION_QUALIFICATION.md).

<!-- readme-section:development -->
## Development

Clone and install the development extras:

```bash
git clone https://github.com/Xalzeroph/Noetrium.git
cd Noetrium
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test,release]"
```

Run the core local checks:

```bash
python -m pytest -q
python scripts/check_readme_i18n.py --all-current
python scripts/public_contract_audit.py
python scripts/no_degradation_audit.py
./deploy/noetrium dev architecture gate
```

Architecture-changing contributions should identify the owning subsystem, preserve fail-closed behavior, add focused tests, and update maintained documentation in the same change. See [Contributing](CONTRIBUTING.md).

<!-- readme-section:security -->
## Security

Security-sensitive areas include authority-boundary bypass, unsafe external effects, secret exposure, command execution, path traversal, artifact integrity, resource fencing, and recovery behavior that could falsely certify an uncertain result.

Do not publish secrets or exploit details in public issues. Follow the private disclosure process in [Security Policy](SECURITY.md).

<!-- readme-section:citation -->
## Citation

If Noetrium contributes to research results, cite the software metadata in [CITATION.cff](CITATION.cff). Release-specific provenance should additionally record the exact Noetrium version or commit used by the experiment.

<!-- readme-section:license -->
## License

Noetrium is licensed under the [Apache License 2.0](LICENSE). Third-party attribution is recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).


## Community

- [Contributing](CONTRIBUTING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security](SECURITY.md)
- [Support](SUPPORT.md)
- [Citation](CITATION.cff)
