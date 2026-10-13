<!-- readme-nav:start -->
<p align="center">
  <a href="README.md">English</a> ·
  <strong>简体中文</strong>
</p>
<!-- readme-nav:end -->

<!-- readme-locale:zh-CN -->
<!-- readme-source-sha256:18bbf2f6259effae6edeb5633d48407f91dfc8ca348779f54a3e03a4f3615e9c -->

<h1 align="center">Noetrium</h1>

<p align="center">
  <strong>面向 AI Agent 的可复现研究基础设施。</strong><br>
  在上层组合实验，在底层统一维护身份、执行真相、恢复、资源、外部效应、产物与证据。
</p>

<p align="center">
  <a href="https://github.com/Xalzeroph/Noetrium/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/Xalzeroph/Noetrium/ci.yml?branch=main&label=CI"></a>
  <a href="pyproject.toml"><img alt="Version 1.0.0" src="https://img.shields.io/badge/version-1.0.0-blue"></a>
  <a href="https://www.python.org/"><img alt="Python >=3.12" src="https://img.shields.io/badge/Python-%3E%3D3.12-3776AB?logo=python&logoColor=white"></a>
  <a href="LICENSE"><img alt="Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-green"></a>
</p>

<p align="center">
  <a href="#quick-start">快速开始</a> ·
  <a href="docs/INDEX.md">文档</a> ·
  <a href="docs/architecture/SYSTEM_ARCHITECTURE.md">架构</a> ·
  <a href="docs/product/operator/UNIFIED_CLI.md">CLI</a> ·
  <a href="CONTRIBUTING.md">贡献指南</a>
</p>

<!-- readme-section:overview -->
## 概览

Noetrium 是面向严肃 AI Agent 研究的执行基础设施。它用于协调模型、环境、方法、参与者、试验、资源、恢复和证据，同时避免让编排细节本身变成“科学真相”。

公开 Python 接口刻意保持极小：`NoetriumUnit` 描述不可变的研究语义，`run` 将根节点交给平台执行。内部系统之所以更复杂，是因为它负责普通实验脚本经常隐式处理的难题：精确身份、持久化状态转换、有界外部效应、资源准入、恢复、溯源和发布证据。

Noetrium 不是 Agent 框架的替代品。Agent loop、planner、memory、benchmark 逻辑、prompt 和科学假设仍由具体研究项目拥有。Noetrium 提供它们周围的基础设施，使一次运行能够被准确归因、检查、中断、恢复、验证，并在精确源码和绑定条件下复现。

<!-- readme-section:why -->
## 为什么需要 Noetrium？

长时间运行的 Agent 实验常以难以察觉、难以复现的方式失败：进程在不确定的外部动作之后重启；两个 scheduler 对进度判断不一致；模型 endpoint 静默变化；checkpoint 被误当成比执行历史更强的事实；或最终成功结果无法追溯到生成它的精确代码和资源实现。

Noetrium 通过显式所有权处理这些问题：

- 科学状态转换只有一条被接受的执行路径；
- 每个持久化真相域只有一个 owner；
- 研究定义不可变，并冻结精确 binding identity；
- 外部效应具有显式 certainty 与 reconciliation；
- crash recovery 绑定到已接受的 execution cut；
- resource、endpoint、process、service、container 使用 lease 与 fencing 管理；
- artifact、measurement 与 evidence 绑定到产生它们的 run；
- 生成式 governance gate 拒绝重复 authority 和 shadow path。

因此 Noetrium 的定位是 research systems platform，而不是 model call 的便利封装。

<!-- readme-section:capabilities -->
## 核心能力

- **极小公开 API。** 下游 Python 只从 `noetrium` 导入 `NoetriumUnit` 与 `run`。
- **内容寻址的研究组合。** Program、Study、Method、Benchmark、Metric 和嵌套 Portfolio 都是具有精确身份的不可变语义值。
- **单一执行内核。** 可编程研究域统一进入 journal-backed Machine，而不是各自创建 runner 和 checkpoint engine。
- **类型化 Model / Environment 边界。** 科学需求与 provider realization、placement、port、container、host lifecycle 分离。
- **持久化恢复。** Recovery 绑定 Machine cut 与精确 program/binding identity；checkpoint 只是恢复加速器，不构成第二份历史。
- **外部效应确定性。** 外部 mutation 使用 intent、receipt、certainty、reconciliation；未知结果在被证明前始终保持未知。
- **资源所有权。** Compute、GPU、endpoint、process、service、container 和可复用环境实例由 owner authority 通过 lease、generation、fencing 管理。
- **不牺牲语义的并发。** Dependency-aware scheduling、hierarchical fairness、single-flight、共享模型服务与不可变 realization 复用提升吞吐，同时保持 run identity。
- **Evidence-first 实验。** Measurement、artifact、provenance、checkpoint 和 publication evidence 都绑定不可变源码与执行身份。
- **统一 operator CLI。** Workspace、research lifecycle、infrastructure、diagnostics 与 development gate 全部收敛到 `noetrium` 命令树。

详细执行模型见 [System Architecture](docs/architecture/SYSTEM_ARCHITECTURE.md) 和 [Runtime and Deployment](docs/architecture/RUNTIME_AND_DEPLOYMENT.md)。

<!-- readme-section:quick-start -->
<a id="quick-start"></a>
## 快速开始

Noetrium 1.0 的正式运行目标是 Linux/amd64，生产运行时以 Docker 为唯一标准路径。在 Linux Docker 主机的源码 checkout 中：

```bash
./deploy/noetrium infra doctor
./deploy/noetrium workspace init --project /path/to/project
./deploy/noetrium research preflight
./deploy/noetrium run
```

qualified wheel 只是 Docker image 的内部构建/验证产物，同时保留为 SDK/开发接口；它不是 production runtime authority。qualified runtime 内可用的完整公开 Python API 为：

```python
from noetrium import NoetriumUnit, run

root = NoetriumUnit.make_structure(
    "paper",
    traits=("research.portfolio",),
)

report = run(root)
```

从项目目录开始：

```bash
noetrium project create my-paper ./my-paper
cd ./my-paper
noetrium project doctor --project .
noetrium project test --project .
noetrium workspace init --project .
noetrium run
noetrium research status
```

文件系统项目与内存中的 `NoetriumUnit` 根节点进入同一套执行架构。Project layer 负责源码发现和 operator ergonomics，不会创建第二套科学 runtime。

<!-- readme-section:architecture -->
## 架构

Noetrium 将不可变研究语义与可变执行 authority 分离。

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

核心规则很少但严格：科学语义可以模块化，但被接受的执行只有一条路径；provider 执行物理效应但不拥有科学真相；cache 与 telemetry 是 projection 而不是 authority；性能优化可以复用不可变 realization，但必须隔离可变科学状态。

仓库实现是围绕这些 ownership boundary 组织的 modular monolith。公开 `noetrium` package 很薄；内部 subsystem 位于 `noetrium_platform`，可以在稳定公开接口之后继续演进。

详细文档：

- [System Architecture](docs/architecture/SYSTEM_ARCHITECTURE.md) — Unit/Event、Machine、authority、binding、evidence、recovery、scheduling 与扩展规则。
- [Runtime and Deployment](docs/architecture/RUNTIME_AND_DEPLOYMENT.md) — Docker-first 部署、model serving、environment lifecycle、resource ownership、shutdown、crash recovery 与大规模调度。
- [Documentation Index](docs/INDEX.md) — v1.0 维护中的全部文档入口。

<!-- readme-section:cli -->
## 统一 CLI

Noetrium 只有一棵命令树：

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

`noetrium run` 是 `noetrium research run` 的短写。已有 run 会被显式检查或恢复；新的独立执行使用 `--new` 创建。Lifecycle 操作不要求通过删除 journal 或 checkpoint 来“恢复正常”。

Workspace binding、多项目执行、run history、recovery、diagnostics 与 development command 见 [Unified CLI Guide](docs/product/operator/UNIFIED_CLI.md)。

<!-- readme-section:deployment -->
## 部署

Linux server 的标准操作入口是仓库 launcher，它在 deployment environment 中进入同一 CLI hierarchy：

```bash
./deploy/noetrium infra doctor
./deploy/noetrium workspace init --project /path/to/project
./deploy/noetrium research preflight
./deploy/noetrium run
```

Noetrium 支持 Docker-first execution、content-addressed environment image、managed model runtime、显式 host resource admission 与 crash reconciliation。GPU placement、endpoint allocation、service/container lifecycle 与 model-serving concurrency 都属于平台物理层决策，而不是项目科学配置。

在共享服务器或长时间实验中使用前，请阅读 [Runtime and Deployment](docs/architecture/RUNTIME_AND_DEPLOYMENT.md)。

<!-- readme-section:reliability -->
## 可靠性与可复现性

当不确定性可能被错误升级为科学结论时，Noetrium 选择 fail closed。

- mutation 之后发生 timeout，不等于该 mutation 没有发生；
- checkpoint 的 authority 不高于授权它的持久化执行历史；
- recovered run 必须匹配记录中的 program 与 binding identity；
- resource reuse 必须具有精确 identity 和有效 ownership/fencing 状态；
- model 或 environment substitution 不会静默当作等价替代；
- release evidence 只对生成它的精确 source cut 有效。

仓库验证结合 unit/integration test 与 architecture、public-contract、governance、release-distribution gate。正式发布流程见 [Release System](docs/governance/RELEASE_SYSTEM.md) 与 [Distribution Qualification](docs/release/DISTRIBUTION_QUALIFICATION.md)。

<!-- readme-section:development -->
## 开发

克隆并安装开发依赖：

```bash
git clone https://github.com/Xalzeroph/Noetrium.git
cd Noetrium
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test,release]"
```

运行核心本地检查：

```bash
python -m pytest -q
python scripts/check_readme_i18n.py --all-current
python scripts/public_contract_audit.py
python scripts/no_degradation_audit.py
./deploy/noetrium dev architecture gate
```

涉及架构的贡献应先确定 owner subsystem，保持 fail-closed 行为，增加针对性测试，并在同一变更中更新维护中的文档。详见 [Contributing](CONTRIBUTING.md)。

<!-- readme-section:security -->
## 安全

安全敏感区域包括 authority boundary bypass、不安全外部效应、secret exposure、command execution、path traversal、artifact integrity、resource fencing，以及可能错误证明不确定结果的 recovery 行为。

不要在公开 issue 中发布 secret 或 exploit 细节。请遵循 [Security Policy](SECURITY.md) 中的私密披露流程。

<!-- readme-section:citation -->
## 引用

如果 Noetrium 参与生成研究结果，请使用 [CITATION.cff](CITATION.cff) 中的软件元数据。针对具体实验，还应额外记录实际使用的 Noetrium 精确版本或 commit。

<!-- readme-section:license -->
## 许可证

Noetrium 使用 [Apache License 2.0](LICENSE)。第三方 attribution 记录在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。


## 社区

- [参与贡献](CONTRIBUTING.md)
- [行为准则](CODE_OF_CONDUCT.md)
- [安全政策](SECURITY.md)
- [支持](SUPPORT.md)
- [引用](CITATION.cff)
