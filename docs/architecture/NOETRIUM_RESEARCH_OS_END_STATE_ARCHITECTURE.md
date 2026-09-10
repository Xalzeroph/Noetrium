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
