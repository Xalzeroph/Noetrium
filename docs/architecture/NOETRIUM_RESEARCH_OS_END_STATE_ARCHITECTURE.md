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
