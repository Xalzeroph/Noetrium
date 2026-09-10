# Noetrium Research OS：终局架构设计

> Status: Architecture Proposal
> Date: 2026-09-10
> Scope: Noetrium 全系统、VM 家族、Run Kernel、研究执行与可复现性

## 1. 结论先行

Noetrium 的终局形态不是一百多个互相独立的 VM，也不是一个吞噬所有语义的万能 VM。

它应该是一个 Research Operating System：

```text
Noetrium Kernel
└── Experiment VM
    └── Research Run VM
        ├── Method VM
        │   └── Agent Turn VM
        ├── Memory VM
        └── Environment VM
             ↓
        Typed Capability Services
```

核心判断：

- Research Run 是研究执行的业务中心。
- Transition 是所有真实状态变化的最小事实单元。
- Noetrium Kernel 是所有机器的运行、隔离、恢复和证据宿主。
- Method VM 是研究方法执行的核心 VM；现有 UMM 应演化为它。
- Experiment、Agent、Memory、Environment 是不同生命周期和状态语义的机器。
- Model、Tool、Evidence、Artifact、Metrics、Catalog、Policy 是服务或 Provider，不强行 VM 化。

这是一套面向长期生态和研究复现的终局设计，而不是针对当前目录结构的局部重构。

## 2. 借鉴 Linux 与 DSH 的原则

本文把 DSH 的借鉴面理解为 distributed shell / composable shell：命令组合、显式管道、远程执行、流式输出和可定义的失败语义。如果 DSH 指的是其他具体项目，替换参考对象不会改变本架构的核心原则。

### 2.1 Linux 给 Noetrium 的启示

| Linux 设计 | Noetrium 对应物 | 迁移后的原则 |
|---|---|---|
| Kernel / user space | Kernel / VM 与 Service | 权限、调度和状态提交只能由 Kernel 掌握 |
| Process | Machine instance | 每个机器实例有身份、状态、生命周期和资源边界 |
| Syscall | Typed capability call | 外部能力只能通过稳定 ABI 进入 |
| File descriptor | Artifact / Evidence reference | 跨边界传递引用，不共享内部可变对象 |
| Pipe | Typed stream / command channel | 组合通过显式输入输出完成 |
| Signal | Interrupt / cancel / checkpoint command | 控制信号可观测、可恢复、可审计 |
| Namespace | Run / machine / tenant isolation | 状态、资源和权限按作用域隔离 |
| cgroup | Resource budget | CPU、内存、并发、token、工具额度可强制限制 |
| procfs / sysfs | Run introspection surface | 运行中的系统必须可检查，不依赖日志猜测 |
| init / supervisor | Run supervisor | 子机器异常不能静默吞掉，必须有父级处理策略 |

### 2.2 DSH 类系统给 Noetrium 的启示

- 命令应可组合，而不是只能调用深层 Python API。
- 管道必须传递有 schema 的值、事件或引用，而不是无类型字符串。
- fan-out、map、reduce、join、tee、retry、timeout 应是运行时原语。
- 远程执行必须保持同一个 Run/Transition 语义，而不是另起一套 RPC 逻辑。
- 命令失败、部分成功、取消和副作用未知必须是显式结果。
- shell 是用户体验层，不能成为核心真相层。

因此 Noetrium 的 shell 不是 Linux shell 的复制品，而是面向研究执行的 typed research shell。

## 3. 五个核心对象

整个系统应围绕五个稳定概念设计，而不是围绕当前 Python 包路径设计。

| 对象 | 定义 | 必须保证 |
|---|---|---|
| ResearchRun | 一次研究执行的根级聚合 | 可恢复、可审计、可重放 |
| MachineProgram | 一个 VM 要解释执行的不可变程序 | 有版本、有 digest、有 schema |
| Transition | 一次状态转移形成的最小事实 | 输入、前态、后态和副作用可验证 |
| EvidenceBundle | 结果产生过程的证明集合 | 来源、关系、完整性可追溯 |
| Capability | VM 可调用的外部能力 | 明确权限、效果等级和返回契约 |

### 3.1 Transition 是第一公民

每一次真实状态变化都必须形成 Transition。日志、指标和 UI 都只能从 Transition 或其派生视图产生。

```text
before_state_digest
input_digest
program_digest
machine_kind
machine_version
after_state_digest
events
effect_receipts
evidence_refs
artifact_refs
parent_transition_id
```

Transition 的提交是 Kernel 的原子边界：状态快照、journal、effect receipt、证据引用和产物引用必须一起提交，或者全部失败。

### 3.2 引用优先

跨 VM 边界不传递内部可变对象，只传递：

- immutable value
- typed command
- ArtifactRef
- EvidenceRef
- SnapshotRef
- CapabilityResult
- EffectReceipt

这相当于 Noetrium 的 file descriptor：拥有引用，不拥有对方的内存。

## 4. 统一 Machine ABI

所有 VM 都实现同一套生命周期协议，但不共享业务语义。

```python
class Machine:
    def open(self, program, run_context) -> MachineState: ...
    def step(self, command, state) -> Transition: ...
    def checkpoint(self, state) -> Snapshot: ...
    def restore(self, snapshot) -> MachineState: ...
    def replay(self, journal) -> MachineState: ...
    def inspect(self, state) -> Inspection: ...
```

### 4.1 稳定的公共契约

| 契约 | 作用 |
|---|---|
| MachineManifest | machine kind、版本、程序、资源和能力声明 |
| MachineProgram | 不可变的程序或计划 |
| MachineCommand | 对机器提出的显式命令 |
| MachineState | 机器私有的逻辑状态 |
| Transition | 状态转移结果和证明 |
| Snapshot | 加速恢复的状态快照 |
| Journal | append-only 的事实序列 |
| Inspection | 类似 procfs 的可观察状态视图 |

### 4.2 程序、运行时和状态分离

- Program 描述要做什么，不能混入当前运行状态。
- Runtime 描述由哪个 Kernel、Provider、权限和资源配置执行。
- State 描述当前机器进度，必须可序列化和校验。
- Journal 是事实来源；Snapshot 只是恢复加速。
- Materialized view 可以重建，不能成为唯一真相。

### 4.3 Noetrium Intermediate Representation

每个 VM 可以拥有独立指令集，但公共调度使用统一的 NIR envelope：

```text
nir.version
machine.kind
machine.instance_id
program.digest
command.kind
command.payload
parent_transition_id
capability_scope
```

NIR 只统一边界，不试图把实验、方法、Agent、记忆和环境压缩成一种万能业务语言。

## 5. VM 家族与职责边界

### 5.1 Experiment VM

Experiment VM 解释实验计划，不直接拥有单个方法节点的实现。

- 参数空间、trial 矩阵和实验阶段
- baseline、对照组和重复实验
- 随机种子、资源预算和评价指标
- 早停、重试、暂停和实验级决策
- 多个 Research Run VM 的编排

一个 Experiment VM 可以创建很多 Research Run VM；每个子 Run 都通过 SnapshotRef 和 TransitionRef 回传事实。

### 5.2 Research Run VM

Research Run VM 是一次具体研究执行的根级聚合。

- 锁定实验、方法、环境和 Provider 版本
- 维护运行状态和参与者拓扑
- 接收子机器的 Transition
- 统一提交证据、artifact、metric 和 effect
- 产生最终结论或结构化失败

它不包含具体方法语义，只负责一个研究运行的完整性。

### 5.3 Method VM

Method VM 解释方法程序：

- compute、capability、agent、route、checkpoint、interrupt、return
- 有界循环、访问计数和步骤限制
- 方法状态的 schema 校验
- 节点输入、输出和 effect receipt 的绑定
- 方法级 checkpoint、resume 和 replay

现有 Universal Method Machine 应成为 Method VM 的参考实现，而不是全局 Kernel。

### 5.4 Agent Turn VM

Agent Turn VM 是可恢复的认知循环，不是一个不可审计的 callback。

```text
Goal
→ Context Assembly
→ Model Decision
→ Capability Call
→ Observation
→ State Update
→ Next Turn / Return / Interrupt
```

它必须记录：

- model、prompt、context 和 policy 的 digest
- 每次工具调用的输入、输出和 effect receipt
- 每轮状态与下一轮输入
- token、时间、资源和停止原因
- 不确定性、失败和人工介入

Method VM 可以启动 Agent Turn VM，但不能直接读写 Agent VM 的私有状态。

### 5.5 Memory VM

Memory VM 解释记忆演化策略：

- write、read、merge、forget、promote、retract
- 去重、冲突解决和可信度更新
- 来源、时效、版本和 provenance
- 从 journal 重建任意历史记忆状态

数据库、向量库和对象存储只是 Memory VM 的 Provider。

### 5.6 Environment VM

Environment VM 解释环境状态和动作：

```text
EnvironmentState + Action
→ NewEnvironmentState + Observation
```

它适用于仿真、实验设备、机器人、自动化系统和多 Agent 世界。

## 6. Kernel 的不可妥协原则

### 6.1 单一真相源

Kernel 维护 append-only journal；所有当前状态都是 journal 的物化结果。

- journal 是事实
- snapshot 是恢复加速
- cache 是可丢弃数据
- projection 是可重建视图
- log 不是业务真相

### 6.2 单写者与并发

每个 Machine instance 在一个逻辑时刻只有一个 Transition writer。

分布式部署时使用：

- run-scoped lease
- fencing token
- transition sequence
- compare-and-commit
- idempotency key
- duplicate transition detection

网络语义可以是 at-least-once，但状态语义必须通过 transition_id 去重实现等价 exactly-once。

### 6.3 父子机器关系

父机器不共享子机器内存，只保存：

- child machine identity
- child program digest
- child snapshot ref
- child transition range
- child result ref
- child failure policy

父级提交子级结果时，必须把 child transition range 作为自己的 Transition 依赖。

### 6.4 不变量

- 同一个 transition_id 永远只能对应一个 canonical payload。
- 已提交的 Transition 不可原地修改。
- Snapshot 必须指向一个已提交的 transition。
- 恢复后继续运行不得覆盖历史事实。
- 未确认的外部副作用不能被标记为成功。
- 任何最终结果都必须能回溯到 program、input、state 和 evidence。
- VM 不能绕过 Kernel 直接持久化业务状态。

## 7. Capability、Syscall 与副作用

VM 不直接访问网络、文件、模型或数据库。所有外部能力都经过 Kernel 授权的 typed capability。

建议的核心 syscall：

| Syscall | 含义 |
|---|---|
| `capability.call` | 调用一个有权限边界的外部能力 |
| `evidence.emit` | 提交结构化证据引用 |
| `artifact.publish` | 发布不可变产物 |
| `machine.spawn` | 创建子机器 |
| `machine.join` | 等待并收集子机器结果 |
| `machine.checkpoint` | 请求或提交快照 |
| `machine.interrupt` | 可恢复地暂停机器 |
| `machine.inspect` | 获取受限的运行状态视图 |

### 7.1 Effect 两阶段提交

所有有副作用的调用采用：

```text
EffectIntent
→ Provider execution
→ EffectReceipt
→ Kernel commit
```

EffectReceipt 必须区分：

- no effect
- effect confirmed
- effect rejected
- effect possible
- effect unknown

外部系统返回超时不能被自动当作失败或成功；必须进入 reconciliation 状态。

### 7.2 能力安全模型

Capability 不是全局函数，而是带有：

- capability_id
- provider version
- input/output schema
- effect class
- permission scope
- resource budget
- idempotency policy
- evidence policy

VM 只能看到被授予的 capability handle，不能枚举或动态获得全局能力。

## 8. 调度、隔离与分布式执行

### 8.1 Scheduler 的职责

Scheduler 不理解领域业务，只根据机器声明和命令状态做资源决策：

- runnable / blocked / waiting / interrupted / failed / completed
- CPU、内存、GPU、token、网络和工具额度
- 优先级、deadline、fairness 和 backpressure
- retry、timeout、circuit breaker 和 cancellation

领域 VM 负责决定下一步是什么；Scheduler 负责决定什么时候、在哪里、以什么资源执行。

### 8.2 三种隔离

| 隔离 | 保护对象 | 实现方向 |
|---|---|---|
| State isolation | VM 私有状态 | immutable snapshot、single writer |
| Capability isolation | 可调用能力 | capability scope、policy check |
| Resource isolation | 计算与外部资源 | cgroup-like budget、quota、lease |

未来的 worker 可以位于本地进程、容器、远程节点或云任务中，只要遵守同一个 Machine ABI。

### 8.3 远程执行

远程 worker 不拥有研究真相，只执行经过签名和版本锁定的命令。

```text
Kernel
  → signed command envelope
  → remote worker
  → transition candidate
  → Kernel validation and commit
```

worker 崩溃只影响未提交的 candidate，不应破坏已提交的 journal。

### 8.4 失败语义

每个命令必须明确：

- retryable
- compensatable
- idempotent
- requires human approval
- effect unknown
- terminal failure

不能让异常类型本身成为跨语言的协议。跨边界使用稳定 error code、failure phase 和 diagnostic reference。

## 9. Research Shell：Linux 与 DSH 的用户体验层

研究者不应该被迫从 Python 对象图开始使用系统。Noetrium 应提供一个 typed research shell，暂称 `nsh`。

### 9.1 Shell 的核心命令

```text
nsh experiment compile experiment.yaml
nsh run start --program method.nir --seed 42
nsh run inspect run/<run-id>
nsh run pause run/<run-id>
nsh run resume run/<run-id>
nsh run replay run/<run-id> --from transition/<id>
nsh evidence explain run/<run-id>
nsh artifact list run/<run-id>
```

命令只是 Kernel API 的友好投影，不能绕过统一权限、journal 和 evidence。

### 9.2 Typed pipeline

DSH 类组合方式映射为有 schema 的 pipeline：

```text
dataset
  | normalize(schema=sample.v2)
  | method(program=screen.v4)
  | agent(policy=review.v3)
  | evaluate(metric=auc)
  | publish(artifact=report)
```

管道的每一段都是 MachineCommand 或 CapabilityCall，输入输出必须有 schema。

### 9.3 组合原语

- `pipe`：类型兼容的单输入单输出组合
- `fanout`：一个输入生成多个隔离子 Run
- `map`：对集合并行执行同一程序
- `reduce`：按声明的聚合规则合并结果
- `join`：等待多个子机器
- `tee`：同时发送到计算和观察分支
- `checkpoint`：在组合边界创建 SnapshotRef
- `replay`：从指定 Transition 重建状态

shell 不负责定义这些语义；Kernel 和 Machine ABI 才是最终权威。

## 10. Introspection：Noetrium 的 procfs 思路

每个运行、机器和能力都必须有稳定的只读 inspection surface。

概念路径可以是：

```text
/runs/<run-id>/status
/runs/<run-id>/machines
/runs/<run-id>/transitions
/runs/<run-id>/children
/runs/<run-id>/capabilities
/runs/<run-id>/evidence
/runs/<run-id>/artifacts
/runs/<run-id>/replay
```

这些视图必须由 journal 重建，不能依赖某个 worker 的内存。

研究者应该可以从同一个 Run 看到：

- 当前停在哪个 Machine 和 Transition
- 运行了哪一个程序版本
- 使用了哪些模型、工具和数据
- 哪些证据完整，哪些证据缺失
- 哪些副作用已确认，哪些需要 reconcile
- 从当前状态继续运行会发生什么

## 11. Evidence、Artifact 与可复现性

### 11.1 证据不是日志

日志回答发生了什么；EvidenceBundle 必须回答为什么相信这个结果。

EvidenceBundle 应包含：

- claim
- source refs
- derivation refs
- input snapshot refs
- transition refs
- artifact refs
- validation status
- provenance chain

最终结果只有在 evidence policy 满足时才能标记为 complete。

### 11.2 可复现性等级

| 等级 | 语义 |
|---|---|
| replayable | 可从 journal 重建逻辑状态 |
| deterministic | 相同输入和版本产生相同 Transition |
| effect-recorded | 外部副作用已完整记录 |
| environment-replayable | 外部环境也可重建 |
| scientifically-reproducible | 结果、证据和统计解释均可复核 |

VM 必须在 manifest 中声明自己能达到哪一级，不能虚假宣称完全复现。

## 12. 生态与扩展模型

几十万 Star 级别的项目必须让贡献者扩展领域，而不是修改核心 Kernel。

### 12.1 扩展点

| 扩展类型 | 贡献者实现什么 | 是否拥有状态 |
|---|---|---:|
| Machine | 新的领域状态机 | 是 |
| MachineProgram | 某类研究计划或策略 | 否 |
| Capability Provider | 新的模型、工具或计算能力 | 通常否 |
| Evidence Resolver | 新的证据校验器 | 否 |
| Artifact Provider | 新的存储或格式 | 否 |
| Scheduler Plugin | 新的资源调度策略 | Kernel 受控 |
| Projection | 新的查询、指标或 UI 视图 | 否 |
| Shell Command | 新的用户命令投影 | 否 |

### 12.2 插件必须提供 manifest

```text
plugin_id
plugin_version
api_version
machine_kinds
capabilities
input_schemas
output_schemas
effect_classes
resource_requirements
replay_level
security_policy
```

插件加载不等于获得权限。权限由 Run 的 capability scope 和 Kernel policy 决定。

### 12.3 版本绑定

每个 Run 创建时锁定：

- Kernel ABI version
- machine implementation digest
- program digest
- capability provider versions
- schema versions
- environment version
- policy version

运行中禁止隐式 hot reload；升级必须创建新版本或显式迁移 Transition。

## 13. 当前一百多个系统的归位规则

系统不能按文件夹名称决定角色，而要按状态所有权和执行语义决定角色。

每个系统必须标注以下字段：

```text
system_id
plane
owner_kind
state_authority
journal_scope
checkpoint_scope
effect_policy
replay_level
public_abi
```

### 13.1 归位分类

| owner_kind | 适用对象 | 状态责任 |
|---|---|---|
| `kernel` | identity、operation、scheduler、journal | 全局运行事实 |
| `experiment_vm` | experiment plan、trial matrix、evaluation | 实验级状态 |
| `run_vm` | research run、participant topology | 单次研究运行 |
| `method_vm` | UMM、workflow method graph | 方法执行状态 |
| `agent_vm` | agent turn、model decision loop | Agent 轮次状态 |
| `memory_vm` | memory evolution、provenance | 记忆状态 |
| `environment_vm` | simulation、device、world state | 环境状态 |
| `service` | evidence、artifact、metrics、catalog | 提供能力或持久化 |
| `provider` | model、tool、database、storage | 接入外部实现 |
| `adapter` | API、CLI、legacy bridge | 协议转换 |
| `projection` | UI、reports、queries、dashboards | 派生视图 |

### 13.2 当前代码到终局边界的映射

| 当前代码族 | 终局归属 |
|---|---|
| `foundation/kernel` | Noetrium Kernel substrate |
| `research/execution/workflow/api/method_machine.py` | Method VM ABI |
| `research/execution/workflow/runtime/method_machine.py` | Method VM reference runtime |
| `research/execution/workflow/implementations/agent_turn` | Agent Turn VM |
| `research/experimentation/run` | Experiment VM 与 Research Run VM |
| `research/experimentation/checkpoint` | Kernel checkpoint plane |
| evidence / ledger | Evidence service |
| artifact stores | Artifact service |
| capability participants | Capability service/provider |

当前路径只是迁移坐标；终局模块应按 owner_kind 和 Machine ABI 重新组织。

## 14. 不可接受的架构模式

以下模式即使短期方便，也不得进入终局核心：

- 巨型 global event bus，所有系统通过字符串事件互相耦合。
- 全局 mutable context，任何插件都可以读写运行状态。
- VM 直接调用模型、工具、数据库或文件系统。
- 日志、缓存或 UI 状态成为研究真相。
- 用 callback 的隐式返回值代替 Transition。
- 用“超时即成功”或“超时即失败”处理未知副作用。
- 运行中隐式替换程序、模型、工具或 schema。
- 让 Evidence 在运行结束后再靠人工拼接。
- 一个 VM 直接修改另一个 VM 的私有 checkpoint。
- 为每一个 CRUD 系统都发明一个 VM 名称。

### 14.1 Kernel 也必须保持小

Kernel 只包含不可替代的通用语义：

- identity
- command dispatch
- transition commit
- journal
- snapshot
- scheduling
- isolation
- effect protocol
- replay
- inspection

实验、方法、Agent、记忆和环境的业务规则必须留在对应 VM。

## 15. 终局建设顺序

虽然不以工作量为约束，但系统仍需要按照语义依赖顺序建设：

### Stage 0：Kernel Contract

- Machine ABI、NIR envelope、Transition、Snapshot、Journal
- canonical encoding、digest、identity、version binding
- capability scope、effect receipt、error taxonomy

### Stage 1：Run Kernel

- Research Run VM
- scheduler、single writer、lease、fencing
- checkpoint、restore、replay、inspection
- evidence/artifact/metric references

### Stage 2：Domain VM Family

- Experiment VM
- Method VM
- Agent Turn VM
- Memory VM
- Environment VM

每个 VM 都必须先定义 Program、State、Command、Transition 和 replay contract，再写 provider。

### Stage 3：Research Shell and SDK

- typed research shell
- Python、TypeScript、Rust SDK
- notebook integration
- program compiler and validation
- local / container / remote worker

### Stage 4：Ecosystem

- plugin registry
- signed manifests
- capability marketplace
- reproducibility bundles
- shared experiment and method libraries

任何新系统如果不能说明自己属于哪个 owner_kind，就不能进入核心仓库。

## 16. 研究者使用模型

研究者只需要理解四个动作：

```text
define  →  run  →  inspect  →  replay
```

### define

声明实验计划、方法程序、Agent 策略、环境和指标。所有输入都被编译成带 digest 的 Program。

### run

Kernel 创建 Research Run，锁定版本，按资源和权限调度子机器。

### inspect

研究者查看状态、Transition、证据、artifact、资源使用、失败原因和可恢复位置。

### replay

研究者可以从整个 Run、某个 Snapshot 或某个 Transition 开始重放，并明确哪些外部输入来自录制、哪些来自实时 Provider。

研究者不应该知道：

- checkpoint 文件如何组织
- worker 在哪台机器
- Provider 如何连接数据库
- VM 内部对象如何布局
- UI 如何订阅状态

这些都属于 Kernel、VM runtime 或 service implementation。

## 17. 终局决策

本设计正式采用以下边界：

1. Noetrium 是 Research Operating System。
2. Research Run 是业务中心。
3. Transition 是事实中心。
4. Noetrium Kernel 是运行中心。
5. Experiment、Run、Method、Agent、Memory、Environment 是机器家族。
6. Method VM 是当前 UMM 的正式归属。
7. Evidence、Artifact、Capability、Metrics、Catalog、Policy 是 typed services。
8. Shell、SDK、Notebook 是用户体验层，不是真相层。
9. Journal 是事实来源，Snapshot 是恢复加速。
10. 新系统必须明确 owner_kind、状态权威和 replay 等级。

这套边界允许 Noetrium 同时成为研究平台、Agent runtime、实验编排器、仿真平台和可复现科学基础设施，而不需要为每种场景重新发明运行时。

## 18. 第二轮架构裁决：以故障语义约束终局设计

> Revision: R2 / 2026-09-10。本文第 1–17 节保持原样。
> 本节及后续章节是追加的规范性裁决；与前文冲突时，以 R2 为准。
> 这是目标设计，不代表现有代码已实现，也不代表已完成全部系统逐项审计。
> 不保留旧 API 兼容层；但历史研究记录的解释能力、数据来源与访问安全不可被当成兼容包袱删除。

“最强”定义为可证明的安全性、可解释的失败、可扩展的执行和低认知成本。
Star 数不能由架构保证；架构质量应由故障注入、复现能力、扩展独立性和真实研究工作负载衡量。

### 18.1 对前文的六项明确修正

| 前文表述 | R2 裁决 |
|---|---|
| 状态、snapshot、artifact、外部 effect 全部原子提交 | 只有同一提交权威中的元数据事务原子化；外部系统采用 intent、receipt、reconciliation |
| Transition 去重实现 exactly-once | 只保证特定 machine revision 的一次接受；外部效果还依赖 Provider 的幂等与恢复协议 |
| Environment 必须精确恢复 | 仿真可声明快照恢复；真实世界通常只能记录观察、校准、补偿或重新初始化 |
| 所有指标和检查都从 journal 重建 | 语义状态可重建；CPU、连接、worker 心跳属于带时效的实时观测 |
| 每个 Research Run 都有独立 Run VM | Run 是执行聚合及监督作用域；不再额外叠加一套与 Kernel 重复的生命周期解释器 |
| 一个固定 VM 树覆盖全部关系 | 监督关系是树，数据依赖和证据来源是图；三者不能混用 |

### 18.2 Linux、Temporal、数据库借鉴边界

Linux cgroup v2 的可借鉴点是分层资源约束与委派，子域不能突破祖先限制；这不等于 Noetrium 已拥有 OS 隔离能力。[Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)
Temporal 的 event history 提供工作流执行历史模型；Noetrium 借鉴记录决定执行所需事实，不把所有业务数据都塞入历史。[Temporal Event History](https://docs.temporal.io/workflow-execution/event)
PostgreSQL 的 Serializable 隔离仍可能要求应用重试事务；Noetrium 的提交接口必须把冲突作为显式结果。[PostgreSQL Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
以下协议均是 Noetrium 的设计推导，不声称上述项目实现了本规范。DSH 具体项目尚未确认，继续仅作为 shell 组合方向的暂称。

## 19. 终局结构：小内核、领域解释器、可替换执行面

### 19.1 五个平面与唯一权威

| 平面 | 负责 | 明确不负责 |
|---|---|---|
| Definition | 类型、程序、编译、依赖闭包与锁定 | 当前运行状态 |
| Control | 准入、身份、授权、revision 提交、监督、恢复 | 大规模张量计算与领域决策 |
| Execution | 受限 worker、领域解释器、效果执行 | 自行确认权威提交 |
| Data & Evidence | 不可变产物、事实记录、来源关系、保留策略 | 替方法决定下一步 |
| Experience | SDK、CLI、Notebook、查询与调试 | 第二套执行语义 |

Kernel 是协议与提交权威，不意味着一个全局进程、数据库锁或集中瓶颈。
同一协议可部署为本地嵌入式运行时或分片集群；部署变化不得暗中降低持久性与权限保证。
Scheduler 的放置策略可替换，提交校验、权限检查和 fencing 不可被插件替换掉。

### 19.2 Machine 与 VM 分开定义

Machine 是拥有身份、私有逻辑状态和提交序列的实例。
VM 是解释某种版本化 Program 的执行语义；有状态不等于必须发明指令集。
Method VM 是通用研究控制程序的解释器，Agent 和 Experiment 可以是同一机制上的领域语言。
Agent 只有在轮次状态、暂停和恢复责任确实独立时才创建独立 Machine；简单模型调用是 Capability。
Memory 默认是带版本的状态服务；记忆整理、晋升、冲突处理程序可成为 Memory Evolution Machine。
Environment 分成仿真 Machine 与真实设备 Session；不得用同一个 restore 标志掩盖物理差异。
领域语言可编译到共享控制 IR，但领域状态 schema、错误语义、证据规则仍独立。
不预设 VM 数量是六个，也不以 VM 数量作为模块质量指标。

### 19.3 三种拓扑

监督树决定创建、取消、预算和故障归属；每个活跃子 Machine 有一个明确 supervisor。
数据依赖图决定输入来自哪里、何时可运行；流与反馈回路必须声明容量和终止规则。
证据图决定结论依赖什么；通过版本化引用连接，不依赖运行树位置。
共享 Memory/Environment 服务可以被多 Run 使用，但写入必须经过独立 owner 与并发协议。
机器迁移和监督权转移记录 authority epoch；不能悄悄脱离父级成为无人负责的后台任务。

## 20. 统一计算契约：决定、执行、提交分离

领域程序的核心接口应为纯语义函数：
`decide(program_ref, state, recorded_input) -> TransitionProposal`。
Proposal 包含 state_delta、commands、output_refs 和等待条件；它不是已提交事实。
外部调用不能发生在 decide 内部；由已持久化 command 驱动执行器完成，再成为新的 recorded_input。
大规模纯计算也可卸载成任务，其结果通过内容引用进入下一步，不强迫解释器执行张量循环。

### 20.1 最小记录结构

| 对象 | 必须携带 |
|---|---|
| Command | command_id、machine_id、expected_revision、payload_digest、scope、deadline |
| Attempt | attempt_id、command_id、worker_id、authority_epoch |
| Proposal | base_revision、input_refs、state_delta_ref、emitted_commands、program_lock |
| Commit | machine_id、new_revision、proposal_digest、previous_commit_ref、causal_refs |
| Snapshot | machine_id、revision、state_root、schema_id、program_lock、integrity_digest |
| Result | value_ref、execution_status、evidence_status、effect_status、reproduction_profile |

command_id 表示逻辑操作，attempt_id 表示尝试；重试不产生新的逻辑外部效果身份。
同一个 command_id 配不同 payload 必须拒绝，不能静默当成重复成功。
墙钟时间只作审计属性；排序依据 revision 与因果关系，不以时间戳判断先后。
跨 Machine 不建立无必要的全局全序；共享资源约束由该资源 owner 串行化。
Kernel 验证权限、revision、类型、预算与引用完整性，不自动证明任意 worker 计算结果正确。
需要可信计算的任务另行声明校验器、冗余执行或隔离信任配置；签名只能证明发送者。

## 21. 提交与外部效果：取消虚假的全局事务

### 21.1 单 Machine 提交协议

1. 将大型状态块和产物写入不可变存储，验证 digest 与所声明的持久性。
2. 事务性校验 machine revision、authority epoch、command 去重和预算预留。
3. 原子写入 Commit、状态 head、输入消费标记、outbox 命令与必要引用。
4. 提交成功后确认；outbox 可重复投递，消费者以稳定命令身份去重。
5. 未被提交引用的预写入对象成为待 GC 对象，不对外宣称为成功产物。

Snapshot 可以延后生成；恢复使用已验证 Snapshot 加后续 Commit。
Commit 必须包含足以应用状态变更的事实或不可变引用，不能只有无法恢复内容的 digest。
丢失响应后的重试先查询 command 提交记录，禁止先执行业务再检查是否重复。
单写者指唯一被接受的提交序列；多个 worker 可以计算候选，只有满足 CAS 的候选可提交。

### 21.2 外部效果协议不是通用两阶段提交

`IntentCommitted -> Dispatch -> ReceiptRecorded -> OutcomeApplied` 是恢复状态机，不是跨数据库和设备的 2PC。
Intent 包含请求 digest、稳定幂等键、目标资源、权限与重试策略。
Provider 已执行而 receipt 未记录时，状态是 UNKNOWN；Kernel 不能靠重试次数推断真实世界。
Provider 支持幂等键及结果查询时可恢复确认；否则进入核对或人工处置，禁止盲目再次执行。
fencing 只有被目标资源实际验证时才能阻止过期 worker 的外部写入。
取消停止后续调度，但不能撤销已经发生的外部效果；补偿是新的操作，不是抹除历史。
对安全关键设备另设硬件互锁、紧急停止和独立授权；通用 VM 不承担实时安全控制保证。

### 21.3 崩溃推演

| 崩溃位置 | 恢复动作 | 不变量 |
|---|---|---|
| 产物已写、Commit 未写 | 重算或复用已验证对象；延后回收孤儿 | 不产生虚假成功 |
| Commit 已写、响应丢失 | 按 command_id 返回原 Commit | 不重复应用状态 |
| Intent 已写、尚未投递 | outbox 恢复投递 | 不丢命令 |
| 外部效果完成、receipt 丢失 | 查询 Provider 或进入 UNKNOWN | 不盲目重放副作用 |
| 子机器成功、父机器未消费 | 重投结果通知，父级 inbox 去重 | 子成功事实不撤销 |
| lease 过期、旧 worker 返回 | 拒绝旧 epoch 的提交并核对效果 | 不覆盖新 owner 状态 |

## 22. 结构化并发、流和预算守恒

父级必须声明子任务完成策略：all、quorum、first-success 或允许部分结果。
first-success 不能默认安全地用于非幂等效果任务；失败分支也必须核对残留副作用。
父级完成前必须 join、取消并确认，或显式移交子任务监督权。
设置独立 reconciliation 状态，不能把“取消已请求”显示成“外部任务已终止”。
等待图必须支持循环检测或有界 deadline；取消和资源清理有保留执行配额。
数据流使用 bounded channel、credit/backpressure、分区 offset 和明确的消费确认点。
流式模型 token 默认是临时观察；最终消息作为语义输入提交。若要据部分输出决策，必须持久化对应片段边界。
fanout 不得复制父级全部额度；采用 reserve、consume、release，并对并发预留事务校验。
外部计费不可强制精准截断时，预算区分 hard enforceable 与 estimated，并预留最坏风险。
调度支持租户公平、数据局部性、deadline 和重试上限；禁止无限重试耗尽全局资源。

## 23. Replay、Fork 与研究有效性

### 23.1 四种操作不能混称 replay

| 模式 | 读取什么 | 是否产生外部效果 |
|---|---|---|
| Reconstruct | Commit 与状态增量 | 否 |
| Verify | 锁定程序和录制输入，重算并比对 | 否 |
| Re-execute | 原始配置与新的真实执行 | 可能；创建新 Run |
| Fork | 指定历史边界与显式变更 | 默认隔离；需重新授予能力 |

随机数、时钟、模型输出、检索结果、并发 winner 和环境观察都是潜在非确定输入。
记录这些输入或声明无法重算；随机种子本身不保证 GPU 与外部模型确定性。
跨机器 checkpoint 是记录通道 offset、in-flight 消息与子状态引用的一致性切面，不是随便拼几个最新快照。
Fork 必须创建新身份、预算和外部幂等命名空间；记录与源 Run 的派生关系。
Memory 分叉使用固定版本或 copy-on-write；真实设备分叉不得假装克隆物理世界。
训练集、测试集、检索快照、评估器版本、单位、样本身份和数据排除规则纳入研究锁文件。
科学复现另需统计设计和独立验证，不能因 journal 完整就标为“科学结论成立”。
执行成功、证据完整、统计有效、可复现是独立状态维度，不压成一个 success 布尔值。
评估过程可作为独立 Machine 生成证据，方法作者不能自行把未经验证的结果标成已验证。

## 24. 存储、隐私与安全不是 VM 的附属功能

Journal 记录必要控制事实及引用；大型数据、prompt、模型回复进入受访问控制的产物域。
同租户可按策略去重；不默认跨租户按内容去重，避免存在性与大小侧信道。
hash 保证内容一致性，不证明来源真实、执行正确或科学有效。
加密、签名、访问控制与 provenance 分别解决不同问题；秘密不得明文写入 journal。
不可变语义历史不意味着敏感内容永久保留；支持保留期限、删除、撤回和密钥销毁策略。
删除后记录 availability/replay degraded，不声称仍能完整重放；受限元数据也需纳入治理。
GC 以活跃 Run、固定快照、发布结果和导出包为根，配合在途写入保护和保留窗口。
inspect 分为 durable semantic view 与 volatile runtime view，两者都显示 revision 或观测时间。
不可信插件必须在进程、容器或其他经过验证的沙箱中执行；Python Protocol 和 manifest 不是安全边界。
权限委派只允许收窄，句柄绑定主体、Run、资源与有效期；实际调用时重新验证撤销状态。

## 25. 编译、程序身份与开发者体验

研究者使用 Method、Study、Dataset、Evaluator 等领域对象；不要求先学习 Kernel 与 NIR。
SDK、Notebook、CLI 都编译到同一 Program 和调用协议；nsh 是投影而非独立事实来源。
编译流水线：领域定义 -> 类型化领域 IR -> 验证 -> 控制执行计划 -> ProgramLock。
NIR envelope 只是封装，不足以称为完整 IR；正式 IR 需要类型、控制流、效果、source map 和版本规则。
ProgramLock 固定代码包、依赖闭包、schema、解释器、数据快照与配置，不能只 hash 函数源码。
静态检查包括类型匹配、能力声明、效果等级、可恢复边界和有界性声明。
动态脚本的终止性通常无法静态保证，必须有运行时预算；不声称编译器能证明任意 Python 程序安全。
纯计算可融合或向量化以降低开销，但保留逻辑来源映射；不可跨效果或持久等待边界随意重排。
断点、single-step、状态 diff、因果 trace 和历史 fork 均基于相同协议。
发布包附带运行配置、证据索引、schema 与所需解释器说明；不可获得的外部数据明确标注。
旧 API 不兼容不等于旧证据失去解释器；历史解码器以只读隔离包保存，不污染新运行 API。

## 26. 一百多个系统的审计规则：不按名字发明 VM

以下是归类验收规则，不是已完成的逐系统映射。只有读取实际 catalog 与实现后才能产出完整清单。
每项记录 system_id、源码位置、领域职责、状态 owner、写入入口、事务边界、效果、恢复模式和删除/合并决定。
service 可以拥有持久状态；区分“提供服务”和“解释程序”，不能用是否有状态作唯一 VM 判据。
跨系统事务需求必须显式暴露：若总要同步提交，优先合并同一 authority；否则采用已定义的消息协议。
同一语义状态只设一个 owner；SQL 表、缓存、索引和 UI 不能各自宣称为原始事实。
不为每个类或模块创建进程；逻辑边界、故障边界、部署边界独立决策。
先按所有权合并重复系统，再决定哪些领域值得专用 Program；拒绝一系统一 VM 的机械转换。

## 27. 以可执行验收定义“最强”

### 27.1 必须通过的模型与性质测试

| 性质 | 验证方式 |
|---|---|
| 同 revision 只有一个 Commit 被接受 | 并发 CAS、网络分区和 fencing 历史检查 |
| 已确认提交恢复后仍存在 | 每个持久化边界断电/进程 kill 注入 |
| 恢复状态等于连续执行状态 | Snapshot + tail 与完整历史的差分测试 |
| 逻辑命令重复不重复消费输入 | 重复投递、响应丢失、乱序组合测试 |
| UNKNOWN 不自动变成 confirmed | Provider 超时及查询失败注入 |
| 父级无遗留无人监管任务 | 取消、worker 丢失与监督权转移测试 |
| 子任务不突破父级预算与权限 | 并发预留、嵌套委派及恶意插件测试 |
| Fork 不意外污染源 Memory/设备 | 隔离和效果授权测试 |
| SDK/worker 实现语义一致 | 跨实现 golden history 与 ABI conformance suite |

用小状态空间模型检查提交、租约、outbox/inbox 与取消协议；模型假设必须与实际存储实现对应。
基准矩阵覆盖短计算、长 Agent、百万 trial、流式环境和大产物，报告吞吐、P99、恢复时间、写放大与存储成本。
性能目标在测量前登记，不编造“零开销”“无限扩展”；优化不得跳过权威提交和效果核对。
通过条件必须包含 safety 与 liveness：既不产生错误事实，也能在规定依赖恢复后继续推进。
离线本地模式、单机服务、分布式 worker 运行同一套语义测试；部署能力差异明确暴露。
所有新增 VM、Provider 和存储后端必须随附故障模型与 conformance 结果，不能只靠 happy-path 单测。

### 27.2 最终收敛

终局不是六层 VM 的固定堆叠，而是小型提交内核承载可组合的领域程序。
Research Run 聚合执行责任；Machine 私有状态和 revision 定义并发边界。
Commit 定义已接受事实；EffectIntent/Receipt 定义现实世界不确定性。
监督树管理生命与预算；数据图管理计算；证据图管理可追溯结论。
领域 SDK 隐藏基础设施复杂性，但不能隐藏副作用未知、证据缺失和无法复现。
下一阶段先完成全量系统所有权矩阵和提交协议可执行模型，再据此重写实现。
不新增兼容壳，不复制状态权威，不以更响亮的 VM 名称替代可验证的协议。

## 28. 第三轮总体架构裁决：研究闭环优先，运行机制服从领域

> Revision: R3 / 2026-09-10。仅追加，不修改第 1–27 节。
> R3 固定总体架构与领域边界；R2 的提交、安全、恢复约束继续有效，明确冲突处以 R3 为准。
> 本轮只制定目标设计，不声称实现完成、性能达标或已逐项审计全部系统。
> 本轮采用原始技术文档与作者论述进行对照；来源支持借鉴点，不为 Noetrium 的组合方案背书。

### 28.1 架构目标函数

Noetrium 的核心价值是：使研究过程可执行、可比较、可分叉、可复核、可共享。
Research OS 是愿景，VM 是机制；两者都不能取代用户价值成为模块划分的唯一依据。
不以系统数量、VM 数量、模式数量、微服务数量或 Star 数作为架构验收指标。
优先级固定为：事实与权限正确 > 研究语义清晰 > 组合与互操作 > 恢复能力 > 工作负载性能 > 便利性。
不保留旧接口兼容壳；保留历史记录可解释性，不把可复核性误当成旧 API 兼容。
未能证明价值的抽象即使实现成本为零，也会造成理解、调试和演化成本，仍应删除。

### 28.2 两个中心，不是一个万能对象

研究层以 Research Graph 为关系模型，回答问题、方法、运行与结论之间有什么联系。
执行层以 Research Run 为责任作用域，回答程序由谁执行、如何监督、失败如何处理。
Graph 不是新的全局可变 context，不是单一事务聚合，不是图数据库选型，也不是调度图。
Run 不负责管理全部研究历史；一次比较可引用多个 Run，一个结论可经历多次独立复核。
研究图谱中的运行派生关系不等同于真实世界的因果关系。
“统一事实”指同一事实有唯一 owner 和可核对身份，不指全平台必须有一份全局日志。

## 29. 总体骨架：五个领域能力与三个稳定接缝

| 领域能力 | 拥有的语义 | 通过什么协作 | 禁止越界 |
|---|---|---|---|
| Research Workspace | 研究对象、Study 定义、人工主张和关系 | 版本化定义与研究引用 | 修改已接受运行事实 |
| Program System | 程序、类型、组合、编译和锁定 | Program package 与执行要求 | 直接调度外部副作用 |
| Execution Fabric | Run、监督、提交、恢复和效果核对 | Run protocol 与结果引用 | 裁定科学结论成立 |
| Evidence & Evaluation | 评估定义、比较规则、证据解释 | 独立评估程序与来源引用 | 把日志完整等同于科学有效 |
| Extension Ecosystem | 可发现、可验证的扩展包及技术适配 | 受版本与权限约束的端口 | 越过 owner 直接写状态 |

这五项是领域能力视图，不替换 R2 的技术平面，也不一一对应五个进程。
例如 Evaluation 的定义位于 Definition 平面，评价执行使用 Execution 平面，结果索引使用 Data 平面。
Workspace 包含无 UI 的领域服务；Web 页面、CLI、Notebook 都只是它的入口。
Extension Ecosystem 是横跨能力边界的扩展方式，不是集中代理全部调用的总线。

最小稳定接缝只有三组：
1. Program contract：运行前，明确执行什么、需要什么以及能保证什么。
2. Run contract：运行中，明确接受、监督、控制、提交与完成的语义。
3. Research record contract：运行后与跨运行，明确结果身份、来源、比较和发布引用。

接缝是多个类型化协议组成的协议族，不是一个万能 JSON 接口。
领域模型允许差异，不能为了统一命名把 Study、Agent 和设备状态塞进同一个超级对象。
这是一种“窄公共协议、丰富两端实现”的设计推导，不要求所有解释器采用相同内部表示。

## 30. 模式选择：每个模式必须对应问题、边界与退出条件

| 模式或思想 | 解决的问题 | Noetrium 采用位置 | 明确拒绝 |
|---|---|---|---|
| Bounded Context | 不同领域词义与规则混淆 | Workspace、Program、Execution、Evaluation 边界 | 全局统一巨型领域模型 |
| Ports & Adapters | 业务被 UI、数据库、Provider 绑死 | 领域服务与外部能力之间 | 每个内部函数都增加接口层 |
| Functional core / effectful shell | 决策与 I/O 混杂，难以重放 | R2 的 decide 与外部执行边界 | 假装包装函数能消除隐藏副作用 |
| CQRS | 更新模型与跨 Run 查询模型差异 | Run 命令与图谱/比较读模型 | 所有 CRUD 强行 CQRS |
| Event-sourced execution | 运行历史、恢复和状态来源不清 | 托管执行的语义提交记录 | 所有业务表强制事件溯源 |
| Supervision / structured concurrency | 无人负责的失败与后台任务 | Run 与子任务生命周期 | 一个 actor 对应一个类，或无限自动重启 |
| Multi-level IR | 高层研究语义过早丢失 | 领域程序到控制计划的分阶段 lowering | 一个万能指令集吞掉所有计算 |
| Content-addressed reuse | 重复计算、版本漂移 | 已声明依赖的确定性任务与产物 | 相同输入文本就复用任意模型结果 |
| Strategy / Interpreter / Adapter | 独立替换决策规则和实现 | 评估器、领域解释器与 Provider | 不同保证的实现被包装成完全等价 |
| Snapshot / branch | 探索变体却丢失来源 | Research Fork 和状态服务版本 | 自动合并物理效果或冲突结论 |
| Saga-like reconciliation | 外部动作无法加入本地事务 | 多阶段有副作用研究任务 | 把补偿说成原子回滚 |
| Architecture fitness functions | 文档边界逐渐失效 | 导入检查、契约测试、故障场景 | 以口号或目录命名代替验证 |

Bounded Context 强调显式的模型边界；本文据此划分领域，不要求技术层之间共享同一个业务模型。[Fowler: Bounded Context](https://martinfowler.com/bliki/BoundedContext.html)
Ports & Adapters 将应用逻辑与输入设备、存储等外部技术隔离；本文采用其可替换入口及可独立测试目标。[Cockburn: Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture)
CQRS 的作者论述明确提示选择性采用和复杂性风险；本文仅在有明确读写差异的上下文采用。[Fowler: CQRS](https://martinfowler.com/bliki/CQRS.html)
其余表格中的 Noetrium 位置与拒绝条件是本设计的工程判断，不是引用来源的原话。

## 31. 研究对象模型：结果、证据和主张必须分离

研究者优先面对六个入口概念：Program、Study、Run、Result、Comparison、Research Package。
Dataset、Evaluator、Environment 是可替换的领域依赖；Machine、Commit、Journal 是高级运行接口。
Question、Hypothesis、Claim 支持研究组织，但不是运行一个简单函数前必须填写的表单。

| 对象 | 语义 | 权威与变更 |
|---|---|---|
| Program | 研究方法或计算的定义 | 发布版本不可变；编辑产生新版本 |
| Study | 比较问题、变量、纳入规则和评价安排 | 锁定的计划与实际偏离分开记录 |
| Run | 一次执行责任及事实索引 | 运行 owner 通过 R2 协议提交 |
| Result | 一次执行的输出与状态 | 不能自带“科学结论正确”的默认含义 |
| Evidence | 支持检查来源、过程或判断的材料 | 记录产生者、版本与可用性 |
| Comparison | 在指定规则下比较一组结果 | 输入集合与评估程序均固定版本 |
| Claim | 对结果提出的可争议主张 | 记录作者、依据、适用范围、撤回或修订 |
| Research Package | 可交换的研究版本及依赖清单 | 发布快照，不是全部平台数据库 |

Research Graph 是上述对象及关系的组合视图；人工创作关系由 Workspace 管理，运行来源关系从对应 owner 的事实投影。
图索引丢失可以重建派生关系，但不能凭 Run journal 重建未被记录的人工假设和批注。
读模型标明索引进度；发布 Comparison 时固定输入引用，不能悄悄使用查询过程中不断变化的“最新结果”。
派生、使用、生成、归属等来源概念参考 W3C PROV；主张是否成立仍由领域评价负责。[W3C PROV Overview](https://www.w3.org/TR/prov-overview/)

## 32. Program System：保留语义，延迟执行选择

### 32.1 三种组合必须独立表达

行为组合：方法调用子方法、Agent、能力或计算任务。
实验组合：在变量、样本、种子与约束上构造试验和对照。
评价组合：对结果进行校验、聚合、统计解释与人工复核。
三者通过版本化契约连接，不能把评价规则埋在方法内部，也不能把整个 Study 压成一次巨大方法调用。

采用分阶段表示：领域定义 -> 领域 IR -> 可执行控制计划 -> worker 任务。
高层 IR 保留 trial、sample、evaluation、human-decision 等语义；底层计划表达等待、调用、并发和恢复边界。
MLIR 的多层表示与渐进 lowering 为此提供设计启发，但本方案不承诺采用 LLVM/MLIR 作为实现依赖。[MLIR Rationale](https://mlir.llvm.org/docs/Rationale/Rationale/)
原生数值计算、训练循环和求解器保留自己的执行引擎；控制计划引用这些任务，不逐条解释所有数值运算。
长期自适应实验可以逐步生成下一批任务；每次扩展必须留下决策输入与版本，不能要求预先展开无限静态 DAG。

### 32.2 三种接入深度，而非三套互不兼容的框架

| 接入深度 | 研究者提供 | 可承诺范围 |
|---|---|---|
| Wrapped task | 已有函数、脚本或容器的输入输出边界 | 外围身份、产物和尝试记录；内部未知效果与恢复不作保证 |
| Structured program | 步骤、依赖、能力和恢复边界 | 明确边界内的检查、重试、复用和暂停 |
| Managed program | 完整托管决策与效果协议 | R2 约束下的提交恢复、录制输入与效果核对 |

支持外部代码不等于兼容旧 Noetrium API；它是生态接入能力。
接入深度与沙箱安全正交：Wrapped task 也必须接受权限隔离，Managed program 也不能自动被信任。
所有接入方式公开保证清单；组合程序的保证按路径与依赖推导，不能由最强子组件替整体背书。
Provider 缺失或后端不能满足要求时明确拒绝或由用户接受降级，禁止静默改变实验条件。
缓存命中记录复用来源；它不是新的独立重复实验，不能增加统计样本数。
Bazel 的 action cache/CAS 及其环境依赖风险说明复用必须锁定实际输入与工具依赖；本文据此限制缓存范围。[Bazel Remote Caching](https://bazel.build/remote/caching)

## 33. Execution Fabric：稳定语义、可分布部署、单一运行权威

Kernel 保留准入、监督、提交校验和效果恢复规则，不负责研究方法、科学评价或所有资源放置算法。
运行语义与部署拓扑分开：本地、团队服务器、集群可使用相同 Program/Run/Result 契约。
不同部署仍可能拥有不同持久性和隔离等级，必须公开；API 一致不意味着故障能力完全相同。

### 33.1 控制与计算分开，不拆散权威

控制执行负责长期等待、任务依赖、取消和已接受进度。
计算执行负责批处理、GPU、模型、工具和设备交互。
产物沿数据路径直接访问受授权存储，不必由 Kernel 中转；控制路径只携带必要身份与引用。
基于历史重建控制执行可借鉴 Temporal；其命令与历史校验思路不能推出任意外部效果自动只执行一次。[Temporal Workflow Execution](https://docs.temporal.io/workflow-execution)

若接入既有持久工作流后端，必须选择一种权威模式：
- Kernel-owned：Noetrium 持有提交权威，后端只是任务执行或资源适配。
- Backend-owned：后端提供经过契约验证的持久执行权威，Noetrium 维护研究记录映射与查询投影。
同一个 Run 不能让两个独立 journal 同时决定下一步；后端不能满足 R2 条件时不得声称等价实现。

### 33.2 独立故障域，而非默认微服务化

部署可以按租户或 Run 划分 cell，每个 cell 具有明确的运行权威、存储和故障责任。
跨 cell 交换不可变引用与明确消息，不建立每次提交都依赖全局图数据库的协调路径。
联邦研究合作以显式导出、授权引用和结果交换为基础，不假装存在跨机构全局事务。
模块默认可同进程部署；只有资源、隔离、可用性或独立运维需求才推动拆分。
监督策略借鉴 Erlang/OTP 的重启边界与强度上限；外部效果必须先核对，不能照搬进程重启语义。[Erlang Supervisor Behaviour](https://www.erlang.org/doc/system/sup_princ.html)

## 34. Evaluation、Compare、Fork：平台的研究辨识度

Evaluation 是领域权威，不是绕过 Execution Fabric 的第二套执行器。
同一后端可以运行方法与评价，但评价具有独立 Program、身份、输入和结果；是否要求人员或组织独立由 Study 声明。
自适应研究允许评价反馈进入下一轮决策，反馈必须是已记录输入，不允许在线偷偷改写已锁定基线。

Comparison 不只是配置 diff，应明确比较哪些结果、按什么规则、在哪些条件下可比。
改变数据集、评价器、样本筛选或预算时，系统标记差异，不能仍显示为完全可比。
失败、取消、缺失和负结果必须有纳入策略；不能只比较成功样本制造选择偏差。
执行成功、来源完整、评估有效、主张获支持是不同结论；系统不能输出一个通用“可信分”代替解释。

Fork 是研究变体操作：固定源边界、声明改动、生成新身份并重审能力。
分叉后可安全复用确定性子结果，但涉及新环境观察、非确定模型或新评估语义时重新执行。
多个分支的研究定义可显式合并；冲突实验结论只能比较或复核，不能像无冲突文本一样自动合并。
Research Graph 负责保留来源关系，R2 的运行分叉协议负责隔离实际执行。

## 35. 开放生态：让扩展独立于核心发布

贡献者扩展的是 Method、Agent policy、Evaluator、Dataset、Environment、Capability 或执行后端。
新领域包原则上不要求修改 Kernel 分支判断、全局枚举和中央注册表源码。
命名空间、显式发现、包锁定和 capability grants 分别负责命名、安装、版本与授权，不合并为万能 registry。
解释器插件是高权限扩展，必须通过符合性测试和隔离审查；普通方法包不应需要编写解释器。

Reference implementation 用于证明契约可实现，不垄断契约。
Contract conformance 是生态共同边界：第三方实现满足协议，才能声明对应保证。
新版本运行协议可以破坏旧 API，但已发布研究包需说明其解释器版本及可获得性。
导入研究包默认是读取元数据，不自动安装或运行包内代码。
研究包应提供开放的元数据与文件/外部引用清单；RO-Crate 是候选互操作映射，不自动宣称兼容。[RO-Crate Metadata Specification 1.1](https://www.researchobject.org/ro-crate/specification/1.1/)
采用此处固定版本作为参考，不把它宣称为最新版本；正式支持需另外验证导入导出与扩展字段。

## 36. 总体方案的竞争性评审

| 候选方案 | 优点 | 关键缺陷 | 裁决 |
|---|---|---|---|
| 所有系统进入单一 Universal VM | 表面统一 | 领域语义丢失、性能路径与扩展绑死 | 拒绝 |
| 六个或更多固定 VM 层级 | 职责直观 | 生命周期重复，不能表达共享服务及研究图谱 | 仅保留独立语义成立的领域解释器 |
| 百余系统全部微服务化 | 可独立部署 | 模块边界被网络固化，权威与事务过碎 | 拒绝作为默认 |
| 研究图谱直接调度所有活动 | 全局关系可见 | 查询模型成为执行瓶颈与隐式可变状态 | 拒绝 |
| 全平台 Event Sourcing + CQRS | 审计形式一致 | 为简单数据管理引入无益复杂性 | 仅运行事实与必要上下文采用 |
| 普通 workflow 加结果 dashboard | 接入快 | 比较、分叉、证据与研究计划是外围补丁 | 保留为接入路径，不作为总体架构 |
| 领域边界 + 稳定协议 + 可组合程序 + 独立评价 | 可扩展且保留研究语义 | 需要维护领域映射与符合性测试 | 采用 |

本方案不是消除所有复杂性，而是把复杂性放到拥有相应知识与状态权威的位置。
无法同时承诺任意代码透明运行、零接入成本、精确重放和任意外部效果自动恢复。
也无法让所有模块既任意替换又完全不暴露语义差异；替换必须满足契约与保证要求。
“无兼容包袱”用于删除历史偶然结构，不用于删除现实约束。

## 37. 用五种完整研究场景验证总体设计

| 场景 | 必须贯通的架构能力 | 能暴露的设计失败 |
|---|---|---|
| 本地已有脚本做基线 | Wrapped task、Result、独立评价、Comparison | 入口被 Kernel/VM 概念绑架 |
| 多模型 Agent 对比 | 程序替换、工具效果、录制输入、统一评价 | 方法与评价耦合，Provider 偷换条件 |
| 自适应科学计算 | 动态 Study、原生计算、批次评价、预算 | 强制静态 DAG 或逐指令 VM 拖慢计算 |
| 真实设备研究 | Session、审批、效果核对、不可恢复状态 | 误把物理世界当可回滚数据库 |
| 跨团队复核 | 研究包、来源图、缺失引用、授权与重执行 | 结果只能在原作者平台里理解 |

每条场景都必须完成：定义 -> 执行 -> 检查 -> 比较 -> 分叉 -> 分享，且不丢失失败或不确定信息。
用修改传播范围检验边界：换 UI 不改领域；换 Provider 不改方法；新增 evaluator 不改 Kernel。
换执行后端必须跑符合性测试，不能以“SDK 调用成功”代替语义一致。
把某领域拆出部署后，仍只有一个语义 owner；如果出现双重提交权威，视为架构失败。
不为这些场景预编造吞吐和可靠性数字；先固定测量任务与失败条件，再获得数据。

## 38. 架构治理与实现顺序

### 38.1 停止“最新一章天然更强”

本轮后的新增模式必须回答：哪个真实场景失败、哪个不变量缺失、现有边界为什么不能解决。
没有这些证据，不增加 Kernel 职责、VM 种类或全局公共对象。
总体边界进入“待验证基线”，验证前不再用新术语反复改名。
Append-only 文档保留裁决历史；未来实现必须引用具体 revision 与决策，不能同时遵循冲突章节。

### 38.2 下一阶段的交付门槛

1. 全量系统所有权矩阵：读取实际 catalog，逐项决定保留、合并、下沉或删除。
2. 三组稳定接缝的规范：Program、Run、Research record；包含能力边界与错误语义。
3. 最小参考路径：一个方法、一个 Study、一次独立评价、一次比较和分叉、一个研究包。
4. 内核协议模型：验证提交权威、取消、效果未知和监督转移，不先铺开全部 UI。
5. 五种场景与多实现符合性验证：通过后再扩展更多领域包与部署后端。

形式化方法用于检查抽象设计中的并发与故障组合；不能代替实现测试和运维验证。AWS 的实践报告说明精确规范和模型检查能发现仅靠普通设计描述难以暴露的问题。[Use of Formal Methods at AWS](https://lamport.azurewebsites.net/tla/formal-methods-amazon.pdf)
这不是要求把整个框架形式化，而是把最小权威协议建成可检查模型。

### 38.3 总体裁决

Noetrium 的主架构是：研究关系模型、可组合程序系统、可靠执行基础设施、独立评价与证据体系、开放扩展生态。
Research Graph 组织研究关系，Research Run 承担执行责任，Kernel 接受事实，Evaluation 解释结果。
Domain VM 是可选的领域解释机制，不是所有系统的统一归宿。
核心对贡献者提供稳定且可检验的接缝，对研究者提供渐进接入和完整研究闭环。
它的强大应体现为：新方法容易加入，复杂执行有明确边界，失败可以解释，结论能够复核，研究可以离开原平台被理解。

## 39. 第四轮总体裁决：从功能组合走向可验证的承诺

> Revision: R4 / 2026-09-10。仅追加；第 1–38 节保持原样。
> 保留 R3 五项能力和三组协议，不新增顶层 VM、全局服务或公共总线。
> 本轮补齐总体设计中的保证、策略、身份和演化边界；R2 的故障约束继续有效。
> 新裁决来自设计反例与原始文献对照，不是已执行的性能实验或完整形式化证明。

### 39.1 本轮新增决策所针对的具体缺口

| 未闭合的场景 | 既有边界为何仍不够 | R4 裁决 |
|---|---|---|
| 同一个程序迁往不同后端 | 接口相同不代表恢复、隔离与效果语义相同 | 显式核对要求、提供能力、前提和已观察结果 |
| 更换 Provider 后仍使用同一个“程序身份” | 程序语义、执行绑定和尝试身份混在一起 | 区分定义、绑定与运行事实 |
| 高性能执行想绕过通用解释器 | 没有区分可替换策略与不可绕过权威 | 机制与策略分离，直接数据路径仍受授权 |
| 自适应研究根据评价决定下一步 | 实验决策与失败恢复都叫“控制” | 研究决策闭环与运行恢复闭环明确分开 |
| 每轮设计都提出新层或新 VM | 缺少新增公共概念的准入条件 | 最小强制核心、可选配置与变更传播验收 |

“最强”不意味着保证最多，而意味着声明的保证有明确成立条件、执行责任和失效方式。
允许研究者选择不同目标，但权限隔离、事实身份和未知效果不得通过配置被伪装为已经保证。
本轮不重新命名 R3 主架构；重点是让它在不同实现和未来变化中仍有清晰含义。

## 40. 原始设计思想：借鉴什么，不照搬什么

| 来源 | 可借鉴的原理 | Noetrium 的推导 | 不照搬 |
|---|---|---|---|
| End-to-End Arguments | 某些正确性判断依赖端点掌握的应用知识 | Kernel 保证执行事实，领域负责结果意义 | 底层可靠就等于科学结论可靠 |
| RFC 1958 | 小型共通规则支持异构系统合作，设计须接受实践反馈 | 三组协议支撑多 SDK、多解释器、多后端 | 整个系统只有一种业务模型 |
| Lampson 系统设计建议 | 接口要明确、克制且有可理解成本 | 公共核心不承载所有可选特性 | 通用接口掩盖巨大运行成本 |
| Exokernel | 保护与资源管理策略分离 | 强制权威留在宿主，领域策略可替换 | 暴露硬件资源或重写宿主操作系统 |
| Saltzer–Schroeder 保护原则 | 最小权限、默认拒绝、检查访问 | 授权是每次实际使用的边界 | 安装插件或持有名称就等于授权 |

端到端论文讨论功能应放在掌握必要信息的位置；本文将其作为职责放置的类比，不声称它直接论证了科研平台设计。[End-to-End Arguments in System Design](https://web.mit.edu/Saltzer/www/publications/endtoend/endtoend.pdf)
RFC 1958 是历史性的架构指导文档，而非 Noetrium 标准；本文只采纳异构互通、规则克制和实现反馈思想。[RFC 1958](https://www.rfc-editor.org/rfc/rfc1958)
Lampson 将接口视为各方依赖的假设集合，同时讨论简单性、完整性与成本的张力；本文据此要求接口公开保证及重要成本边界。[Hints for Computer System Design](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/acrobat-17.pdf)
Exokernel 分离保护与管理；本文借鉴该分工，不继承论文的硬件接口、实现形式或性能数字。[Exokernel](https://pdos.csail.mit.edu/6.828/2008/readings/engler95exokernel.pdf)
最小权限、默认拒绝与完整访问检查作为安全边界的依据；具体实现仍需适配进程、远程调用与撤销模型。[Basic Principles of Information Protection](https://web.mit.edu/Saltzer/www/publications/protection/Basic.html)

## 41. 两个闭环：探索研究问题与维持可靠执行

### 41.1 研究决策闭环

研究定义提出问题与方法，Study 选择执行，Evaluation 解释结果，研究者或已授权策略决定下一轮。
该闭环允许自适应、人工介入和长期演化；每次改变留下版本、输入和决定的归属。
Workspace 组织研究关系，Study Program 表达决策；Research Graph 本身不触发隐式执行。
人工主张可以存在于无活跃 Run 的研究工作区，单次 Run 也可以不属于复杂 Study。
这保留简单脚本入口，同时支持复杂研究；研究图谱不是使用执行能力的强制前置依赖。

### 41.2 运行恢复闭环

执行要求被准入后，运行宿主调度任务、接受进度、处理故障、核对效果并生成结果记录。
该闭环可以更换 worker、恢复已接受状态或按原策略重试，但不能暗中修改研究条件。
用更便宜的模型替代超时模型不是普通恢复；除非 Program 已声明允许选择及其研究影响，否则必须形成显式变更。
系统决定“是否可以重试”，不等于系统有权决定“这次失败样本是否应从研究中排除”。

### 41.3 两个闭环的连接点

| 方向 | 允许传递 | 不允许传递 |
|---|---|---|
| 研究到执行 | 锁定定义、可选择范围、预算和能力授权请求 | 绕过权限的执行指令 |
| 执行到研究 | 输出、失败、实际绑定、效果状态与来源记录 | 无依据的科学有效性结论 |
| 评价到下一轮 | 版本化评价结果和明确决策输入 | 修改旧结果或静默改写基线 |
| 人工到执行 | 带主体和范围的批准、暂停、变更请求 | 无身份批注直接变成外部动作 |

Noetrium 不需要一个全局“超级 Agent”管理所有闭环；Agent 是可选的研究程序或交互入口。
自治级别取决于授予的权限和 Study 策略，不因为调用者是 AI 就自动扩大。

## 42. 公共协议的核心是保证，而不只是形状一致

### 42.1 四种信息必须区分

Requirement：Program 或 Study 要求什么。
Offer：Provider、解释器、存储和后端承诺什么，以及依赖什么条件。
Admission：当前绑定是否满足可检查要求，哪些项目仍依赖声明或外部假设。
Observation：本次运行实际发生什么，哪些保证受到故障、撤销或数据缺失影响。
这些信息属于现有三组协议，不新增第四套全局保证服务。

保证不能压成单一等级或“最强后端”标签：
持久性、隔离、重放、外部效果核对、数据保密和统计独立性不是同一个维度。
一个后端可能更易恢复，却不满足数据驻留；一个缓存可能减少计算，却不能充当独立重复样本。
必须按任务与执行路径检查组合；不能简单取最弱等级或叠加各插件标签就声称证明整体正确。

### 42.2 组合与替换规则

实现替换不得对原本合法的输入施加未声明的新前提，也不得悄悄降低承诺。
schema 相同只是必要条件之一；时间、单位、顺序、效果类别和终止方式也可能影响语义。
组合验证分为静态可判定项、运行准入项和只能依赖领域检验的假设。
对无法判定的性质返回 unknown 或要求明确接受，不能把通用编译器包装为任意程序证明器。
记录 Offer 与测试依据并不使第三方声明自动可信；受信任边界和实际验证仍需独立表达。
运行中权限撤销、Provider 漂移或输入失效时重新检查相关条件，必要时暂停或降级标记。
降级只能在允许范围内发生并留下记录，不能让 UI 继续显示原保证全部成立。

### 42.3 端到端验证的分工

Kernel 验证提交身份、授权和状态前提；不负责证明任意算法的数学正确性。
数据服务验证内容完整性与可用性；不负责证明数据适合某个研究问题。
Evaluator 验证它声明的指标或规则；不自动证明总体研究设计没有偏差。
Research Package 说明依赖与来源；不因可下载就自动获得“可复现”认证。
明确这些分工不是削弱能力，而是防止一个局部成功被错误提升为端到端成功。

## 43. 分离机制与策略：强内核不是大内核

| 不可绕过的机制 | 可由领域或配置选择的策略 |
|---|---|
| 验证能力使用权限与作用域 | 选择哪些获准工具适合当前问题 |
| 接受唯一合法的状态推进 | 方法下一步如何决策 |
| 持久记录效果意图与核对状态 | 在声明范围内选择重试或人工介入 |
| 实施预算预留与资源边界 | 在合法预算内如何分配试验 |
| 记录程序、绑定与输入事实 | 选择哪些变量构成实验 |
| 保留结果与评价来源关系 | 如何定义指标、比较或主张 |

策略可替换不等于任意 callback：影响研究或执行语义的策略要可识别、可审查、可记录。
不是所有策略都必须编译进 VM；原生库、领域解释器和受限程序均可承载策略。
安全关键路径不依赖插件自愿遵守；宿主或外部安全设备承担实际强制。
通用路径提供安全默认值，专用路径可以做批处理和原生计算，但共享相同授权及结果契约。
高性能数据路径可直接连接受授权存储与计算后端，不以经过 Kernel 代理每个字节证明“统一”。

## 44. 定义、绑定、运行身份：同时保留可移植性与可追溯性

程序可以在多个环境执行，因此程序定义不应把 worker 地址或一次尝试误当成自身语义。
相反，研究复核需要知道实际用了什么，因此也不能只记录一个抽象 Program 名称。

| 层面 | 表达什么 | 变更的意义 |
|---|---|---|
| Definition | 方法、Study、评价规则与允许变化的边界 | 研究定义变化 |
| Binding | 具体数据版本、Provider、执行引擎及策略选择 | 执行条件变化 |
| Execution | Run、实际输入、尝试与接受事实 | 一次具体执行或恢复事件 |

ProgramLock 是可分层引用的锁定清单，不再要求一个不可解释的大 hash 兼任三种身份。
绑定身份覆盖所需的实际实现闭包；底层构建可能因目标平台不同而不同，来源仍关联原定义。
同 Definition 不保证结果完全可比；Comparison 还需检查相关 Binding 与 Evaluation 条件。
同 Binding 也不保证非确定模型输出相同，更不保证多个样本统计独立。
worker 迁移原则上不改变研究定义；若硬件变化影响数值或可重现前提，仍必须进入实际执行记录并按要求处理。
变化来源应可以解释为定义变化、绑定变化或执行差异，而不是只能回答“hash 不一样”。

## 45. 可独立使用的核心与完整发行版

协议、参考实现和产品发行版是三种交付物，不是三个运行权威。
协议定义可互操作边界；参考实现提供可运行基线；发行版把常用领域包、Provider 和体验组装起来。
默认发行版应让研究者直接完成研究闭环，但底层执行库不强制启动 Workspace、图查询服务或 Web 控制台。
高级用户可以仅使用研究记录和评价能力接入外部结果；必须标明哪些执行事实由外部声明、哪些由平台见证。
“能够单独使用”不是任意忽略依赖；每种组合公布最低依赖与可用保证。

### 45.1 三组协议的准入边界

Program 核心只要求识别定义、解释方式、依赖及执行要求；不强迫每个包声明 Agent 或 Memory 概念。
Run 核心只要求明确责任、控制及事实边界；持久重放属于需满足前提的能力配置，不能冒充所有 Wrapped task 的基础保证。
Research record 核心表达结果、来源与引用；不强迫全部研究采用同一种假设或统计学模型。
安全和身份检查不是可选插件；研究领域特性通过显式配置或扩展加入。
新字段如果改变安全、效果或结果解释，旧实现不能忽略；只读展示元数据才可在规则允许时跳过。
新版本可以不兼容旧 API，但必须显式拒绝不支持的语义，而不是容忍解析后错误执行。

### 45.2 核心扩展的准入测试

只有跨多个独立场景反复出现、语义稳定且已有可行实现的机制，才升级为强制公共核心。
只被一种领域需要的概念留在领域包；只有一种 Provider 需要的参数留在适配器。
如果“新增领域”总需要新增 Kernel opcode，应重新审视解释器边界，而不是无限扩充指令枚举。
如果“更换存储”需要研究方法修改业务代码，应重新审视持久化端口。
如果“发布报告”必须重新运行全部实验，应重新审视研究记录与评价/呈现的分离。

## 46. 故障隔离和依赖方向应服务研究闭环

控制提交不能同步依赖图索引、报表、插件市场或全局搜索，否则辅助系统会变成运行单点。
查询与展示故障可以允许执行继续，但已声明必须保存的证据、授权检查和提交存储不可被当作辅助功能跳过。
可用性取舍按本次 Program 的要求决定，不凭模块叫“service”还是“projection”判断。
运行可以暂时无法展示，不能因此伪造完成；结果可以已产生但证据未齐，状态必须区分。
授权在离线模式下采用明确的本地信任策略与有效范围；远程撤销不可达时不承诺实时撤销已生效。

共享资源建立显式 owner，跨域协作通过协议；不建立同时拥有权限、调度、模型路由、图查询的全能协调器。
目录、注册表和名称发现不是运行真相；一次执行锁定所需引用后，不应随市场内容变化而悄悄改变。
平台必须保留数据导出与只读解释路径，避免“研究存在但离开控制台就无法理解”。
跨组织合作可以交换研究记录而不共享运行内核；不要为了互操作强建一个全局数据库。

## 47. 以变更传播而非层数验收整体架构

| 设计压力测试 | 预期改动范围 | 架构失败的表现 |
|---|---|---|
| 添加新的研究方法族 | 领域包、解释或编译扩展、测试 | 修改通用提交协议才能运行 |
| 替换满足契约的模型 Provider | Adapter、Binding 和对应验证 | 方法代码引用 Provider 私有状态 |
| 从本地搬到集群 | 部署、资源绑定、保证准入 | 研究定义被重写为另一套 API |
| 换一种评价方法 | Evaluation Program、新 Comparison | 篡改原始 Run 或重写 Kernel |
| 新增真实设备 | 能力与 Session 适配、安全配置 | 复用仿真 restore 冒充物理恢复 |
| 移除 Web/图索引服务 | Experience/查询不可用或降级 | 正常授权运行无法提交 |
| 两个独立实现交换研究包 | 已公开协议与明确缺失项 | 依赖未说明的私有数据库和隐式对象 |
| 新增严格保密的 Study | 政策要求、受控绑定和验证 | 先运行再由日志过滤器补救泄露 |

以上是待执行的架构试验，不是声称当前系统已通过。
通过标准不是零代码修改，而是改动集中在拥有相应知识的边界，且原有保证不会被无声破坏。
两个实现完成互操作、五类研究场景完成闭环，比再添加一个抽象层更有资格说明设计成熟。
文档继续记录被验证或被推翻的决策；未经验证的总体裁决不能因发布日期较新自动获得“最佳”地位。

### 47.1 R4 的收敛结论

保留五项领域能力、三组协议、小提交内核以及可选领域解释器。
补充两条闭环的责任边界，明确保证组合，以及定义/绑定/运行三类身份。
把“强大”落实为可选择但不虚假的保证、低变更传播、专用实现自由与完整研究可追溯性。
整体架构不是要集中掌握所有能力，而是让各个系统在明确边界内独立发挥能力，同时能组成可核对的研究过程。

## 48. R5 实现基线：把核心裁决落成可运行协议

> Revision: R5 / 2026-09-10。仅追加；此前章节保持原样。
> 本节记录本轮实际提交的代码能力，不把尚未完成的领域适配或部署验证写成已完成。

### 48.1 已实现的公共内核

1. MachineIdentity、MachineProgramRef、MachineCommand、TransitionProposal、MachineCommit、MachineSnapshot 和 MachineInspection 组成稳定的 Machine ABI。
2. MachineCommit 同时绑定 command_digest 与 proposal_digest；同一 command identity 的不同 payload 会被拒绝，重试只在内容完全一致时幂等返回。
3. InMemoryMachineJournal 提供进程内测试基线；DirectoryMachineJournal 提供规范 JSONL、跨进程锁、追加写入、单调 revision、前驱链校验和重启恢复。
4. MachineRuntime 拥有提案到提交的唯一转换路径：解释器只产生 TransitionProposal，Journal 才接受事实。
5. InMemoryMachineSnapshotStore 与 DirectoryMachineSnapshotStore 提供单调、校验、原子发布的 Snapshot；Snapshot 是恢复加速记录，不能绕过 Journal。
6. MachineEnvelope、Outbox、Inbox 和 DeliveryReceipt 把子命令传递从状态提交中分离；重启时可依据 Journal 重建 commit/enqueue 间隙。

### 48.2 已实现的第一条领域接入

现有 UniversalMethodMachine 通过 MethodMachineInterpreter 接入公共 Machine Runtime。节点级方法执行、能力调用、checkpoint、interrupt、evidence 和 loop limit 仍由 Method VM 负责；Machine Runtime 负责运行身份、revision、幂等、提交、恢复和跨机派发。

这确认了“通用方法 VM”不是整个系统唯一的 VM，而是一个遵守公共 Machine ABI 的领域解释器。未来 Run、Agent、Memory、Environment、Evaluation 机器应复用同一核心协议，但保留各自状态语义和能力边界。
### 48.3 本轮验证门槛

本轮新增的 ABI、Runtime、Snapshot、Outbox/Inbox 和 Method adapter 测试全部通过；全仓回归中新增路径通过。全仓仍存在与本次改动无关的 Windows 环境差异：产品入口测试要求未安装的 noetrium 模块，公共 shell 测试硬编码 Unix /bin/sh；这两项不能被解释为 Kernel 或 Machine 实现回归。

实现约束已经固定：不允许领域解释器直接写 Journal；不允许 Provider 成为事实权威；不允许 UI、索引或图谱服务进入提交临界路径；不允许把 unknown effect 伪装成 succeeded；不允许用 Snapshot 取代提交链。
