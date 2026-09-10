# Noetrium–SEM node1 论文实验问题复盘与下游体验优化规格

- 文档日期：2026-09-10
- 适用项目：Noetrium（通用运行时）与 SEM（下游科学语义）联合优化
- 记录范围：Windows Portable Git 同步、node1 拉取、Minecraft 运行时构建、模型 qualification、真实 pilot、完整矩阵启动与失败收尾
- 记录原则：保留可复现事实；不把临时绕过写成正式能力；不记录密码、API key、私钥或其他敏感凭据

## 1. 结论摘要

本轮工作没有得到 claim-ready 的完整论文矩阵。Minecraft pilot 已经真实跑通，证明 Noetrium Minecraft 绑定、Mineflayer bridge、Minecraft server、SEM assignment 和 evidence 产物可以端到端联通；但是完整矩阵 v2 在第一个 assignment 的模型请求阶段因 HTTP transport timeout 退出，退出码为 1，OOM 为 false，postprocess 因此没有标记分析结果为 claim-ready。

本轮暴露的问题主要不在单个算法，而在“下游第一次使用时需要人工猜路径、猜镜像、猜运行环境、手工修复权限、手工刷新 qualification、手工诊断日志”的集成体验。现有 Noetrium 的严格性是有价值的，但失败信息、运行时自描述能力、部署打包和长实验生命周期管理还没有把这种严格性转化为下游可操作的工作流。

后续优化的目标应是：下游只需要声明实验所需的环境和模型能力，Noetrium 自动完成 capability preflight、镜像选择、bridge 依赖解析、日志分流、隔离 reset、qualification 状态检查、可恢复运行和最终 provenance manifest；任何失败都应在开始正式矩阵前，以稳定错误码和明确修复命令暴露。

## 2. 本轮基线与最终状态

### 2.1 代码与部署基线

| 项目 | 事实 |
|---|---|
| Noetrium GitHub main | 5f56cba2da0b2db2f8ff35285fabf8b2fd233c9e |
| SEM GitHub main | 0c015c1916a9e4c82d71fa1783e3284a2c255ac3 |
| Noetrium node1 checkout | /data1/agent-research-runtime/agent-research-platform-system |
| SEM node1 checkout | /data1/agent-research-runtime/agent-research-sem |
| Noetrium node1 当前本地提交 | 31293eebf6f93dd0f12e45f870000a9fcff25f4a |
| Noetrium 本地相对 GitHub | main...origin/main [ahead 1]；该本地 commit 只在 node1，未 push |
| SEM node1 状态 | main，跟随已 push 的 0c015c19... |
| Minecraft 镜像 | noetrium-minecraft:node1-noe-31293eeb |
| Minecraft 镜像 digest | sha256:c11c97a9823832ca64f92457ddc9ebb9ab3aaffd5fae6c9cd709e61eabac0298 |
| 正确构建入口 | docker compose -f deploy/compose.yaml -f deploy/compose.minecraft.yaml build platform-runtime |
| 模型服务 | node1 已运行的 Qwen 3.8 27B 服务，HTTP endpoint 为本机已配置地址；服务进程未停止、未重启 |
| 真实 Minecraft server | vanilla 1.21.1，项目隔离运行目录为 /data1/agent-research-runtime/sem-paper-minecraft-20260910 |
| 完整矩阵结果目录 | /data1/agent-research-runtime/sem-results/joint-20260910-node1-full-v2 |

### 2.2 结果状态

| 运行 | 状态 | 证据 |
|---|---|---|
| direct bridge smoke | 通过 | 22/22 stdout 行均为 JSON object |
| pilot v28 | 通过 pilot 级别 | 12 个任务，evidence closed 12/12；claim_status=pilot_not_claim_ready |
| full v1 | 启动前失败 | qualification receipt 已过期，Noetrium preflight 拒绝 |
| full v2 | 运行后失败 | 2026-09-10 07:23:49 启动，07:35:28 退出，NODE_EXECUTION_FAILED -> ModelEndpointError -> TimeoutError |
| postprocess | 未生成 claim-ready 分析 | watcher 正确记录 full_container_exit=1 并跳过正式分析标记 |

完整矩阵 v2 的失败不是 OOM，也不是 Minecraft bridge JSONL 污染；日志显示失败发生在 SEM 的 UMM assignment 执行期间、模型 endpoint HTTP transport 阶段。这个问题本身也必须纳入后续 Noetrium 的长实验可靠性优化。

## 3. 时间线

| 阶段 | 发生的事情 | 暴露的问题 |
|---|---|---|
| 接手与记忆恢复 | 重新核对 Noetrium、SEM、设计文档和交接文档 | 旧交接中的固定 Noetrium SHA 已被后续决策 supersede，provenance 可能漂移 |
| GitHub 同步 | Windows Portable Git 使用自带 SSH 完成两个仓库 push | GitHub 插件写接口曾返回 403，服务器主线与 GitHub 主线需要人工对齐 |
| node1 拉取 | 建立干净 checkout，避免污染已有 canonical worktree | 服务器存在用户未提交文件，直接 pull/改动有覆盖风险 |
| 测试准备 | 发现默认 shell 没有 python，默认 Python 只有 3.10 | 仓库要求 Python 3.11+，环境探测没有在最前面失败 |
| 测试执行 | 安装 pytest 后改用 Python 3.12 Docker 环境 | 测试依赖和运行时依赖没有由项目入口统一准备 |
| 镜像选择 | 区分通用 Dockerfile 与 Minecraft overlay，构建 MC 镜像 | 部署文档/入口不足以让下游一眼知道该用哪套 compose |
| qualification | 旧 closure 不兼容或过期，重新生成 v2 closure | closure 生命周期短于长实验准备和 pilot，刷新需要人工操作 |
| pilot v15–v24 | 逐个排除 mount、依赖、路径和 bridge 输出问题 | 多个失败都只能通过底层日志和容器试错定位 |
| pilot v28 | 使用修复后的镜像和运行参数完成真实 pilot | 证明主链路可用，但运行耗时长，失败恢复和状态反馈仍弱 |
| full v1 | 正式矩阵 preflight 立即拒绝过期 closure | 严格校验正确，但失败提示不足且没有 launch-time freshness workflow |
| full v2 | 使用新 closure 启动完整矩阵 | 第一个 assignment 的模型 HTTP 请求 timeout，矩阵整体退出，没有 assignment-level resume |

## 4. 全部问题明细

下面每项都区分“临时处理”和“应由 Noetrium 负责的永久能力”。

### P01：GitHub 插件写入返回 403

- 现象：尝试通过 GitHub 插件更新 SEM provenance、README、alignment 和 handoff 时，接口返回 Resource not accessible by integration；没有产生部分提交。
- 根因：当前集成凭据只有读取或不具备目标仓库写权限，不能把“能读 GitHub”推断为“能写 GitHub”。
- 影响：原计划的“插件修改—服务器 pull”链路被阻断；如果不停止并核验，容易误以为远端已经包含修改。
- 临时处理：改为 node1 服务器 checkout 上直接修改并只 commit、不 push；本轮最新文档也遵守这一约束。
- Noetrium/平台改进：提供仓库 provenance 检查脚本，在修改前明确报告 remote、当前 branch、ahead/behind 和写入通道；下游脚本不得假设远端写入成功。
- 验收：写权限失败必须在变更前以结构化错误返回；本地 commit、GitHub commit 和服务器运行 commit 在 manifest 中分别记录。

### P02：canonical checkout 有用户脏文件

- 现象：Noetrium 服务器 canonical tree 存在必须保留的 README 多语言、翻译状态、reference harness 和 nohup.out；SEM 还有 .sem-sync/、results/ 和异常文件。
- 根因：开发工作区、实验结果和用户保留文件没有天然隔离。
- 影响：直接 reset、pull、批量清理或切分支可能覆盖用户工作；无法安全判断哪些文件属于当前任务。
- 临时处理：为 Noetrium 和 SEM 建立干净 node1 checkout/worktree；不触碰原始脏目录，不删除异常文件。
- Noetrium/平台改进：提供 noetrium workspace doctor，将 canonical source、generated results、runtime state、user changes 分成明确 scope；实验命令默认拒绝 dirty checkout，除非显式指定并产生审计记录。
- 验收：dirty tree 时启动命令给出具体文件清单和安全建议；创建的实验 manifest 记录 source tree digest，不依赖未提交内容。

### P03：旧交接文档固定了过时的 Noetrium SHA

- 现象：旧 handoff 要求 SEM 固定 Noetrium 255ca63e，而后续 Noetrium 通用方法机合并结果和 GitHub main 已更新。
- 根因：设计文档、运行时 provenance 和代码依赖没有单一版本权威。
- 影响：可能把旧平台误当联合优化基线，造成接口对齐错误和不可比实验。
- 临时处理：以最新 Noetrium main、SEM main 和后续设计决策为准，重新核对 provenance。
- Noetrium/平台改进：生成 machine-readable compatibility manifest；SEM 只消费 Noetrium public facade 和 schema，不在文档中手工冻结旧 SHA。
- 验收：启动前检查 Noetrium commit、SEM commit、schema digest 和镜像 digest；任一漂移都显示明确的 expected/actual。

### P04：Python 命令与版本不一致

- 现象：服务器没有全局 python；可用用户环境是 Python 3.10；仓库导入 StrEnum 时要求 Python 3.11+。
- 根因：主机 shell、用户虚拟环境、Docker 运行时各自有不同 Python；项目没有在最前面统一做版本 preflight。
- 影响：第一次测试在 collection 阶段失败，浪费诊断时间；下游不知道该使用哪个解释器。
- 临时处理：复用现有 Python 3.12 Docker 环境跑测试和实验，不修改 Qwen 服务。
- Noetrium/平台改进：所有入口先执行统一 runtime doctor，输出 Python、Node、Java、包版本和真实 import 路径；不满足版本时在第一屏给出可复制命令。
- 验收：Python < 3.11 在测试/实验开始前即失败，错误中包含检测到的版本、需要的版本和推荐 Docker/venv 入口。

### P05：pytest 不在可执行环境中

- 现象：服务器只有残缺 pytest bytecode cache，没有可执行 pytest；Docker 镜像也不含 pytest。
- 根因：测试依赖只写在 optional dependency，没有提供“在隔离环境安装并执行”的标准入口。
- 影响：需要先判断是否可安装依赖，测试并未按预期开始。
- 临时处理：只在 Python 3.12 测试环境安装 pytest，不改仓库和生产服务。
- Noetrium/平台改进：提供 noetrium test 或标准 test image；自动显示依赖来源、版本和解释器路径。
- 验收：干净 node1 上一条命令完成依赖检查和测试；测试报告写入独立结果目录，不污染 source tree。

### P06：通用镜像与 Minecraft 镜像选择不明显

- 现象：deploy/Dockerfile 是 Python-only 通用镜像；deploy/Dockerfile.minecraft 才包含 Java、Node、npm 和 Mineflayer bridge。下游需要自行判断并叠加两个 compose 文件。
- 根因：环境 capability 与镜像 profile 的映射没有成为一等配置。
- 影响：容易用 generic image 跑 Minecraft，直到运行时才发现 Java/Node/bridge 缺失。
- 临时处理：确认 MC 使用：docker compose -f deploy/compose.yaml -f deploy/compose.minecraft.yaml build platform-runtime。
- Noetrium/平台改进：根据 environment=minecraft 自动选择 profile；提供 doctor --environment minecraft 和最终 image capability manifest。
- 验收：下游只声明 Minecraft 环境即可得到正确 Dockerfile、overlay、healthcheck 和依赖版本；generic image 对 MC 请求在 preflight 阶段明确拒绝。

### P07：旧预构建 Minecraft 镜像缺少 Mineflayer

- 现象：早期使用的预构建镜像在运行时找不到 mineflayer，不能启动 bridge。
- 根因：镜像 tag 没有绑定完整的 Node 依赖，镜像内容和 tag/provenance 不一致。
- 影响：容器启动后才失败，无法区分代码问题和镜像问题。
- 临时处理：从当前 Noetrium checkout 重新构建带 Node 22、Mineflayer 4.37.1 的镜像，并运行 minecraft-doctor。
- Noetrium/平台改进：镜像构建时执行真实模块解析 smoke；将 Node/npm/Mineflayer/pathfinder/pvp/vec3 版本和 image digest 写进 manifest。
- 验收：镜像 build 失败不得产出可被实验命令接受的 tag；doctor 必须验证 Python 绑定路径和 Node 模块路径是同一套可运行依赖。

### P08：Python 已安装包与源码 bridge 的 node_modules 路径不一致

- 现象：bind_bundled_minecraft_environment() 从已安装的 site-packages 找到 bridge.js，但 npm ci 安装的 node_modules 在 /opt/noetrium 源码树；安装包 bridge 目录旁没有依赖。
- 根因：Python package data 复制了 JS 文件，却没有把 npm 依赖作为同一 runtime artifact 处理；绑定函数也没有消费 MC_BRIDGE_DIR。
- 影响：必须手工设置 NODE_PATH、MC_BRIDGE_DIR，甚至尝试 PYTHONPATH 才能运行；下游体验高度依赖镜像内部布局。
- 临时处理：使用源码 bridge root，并显式设置 NODE_PATH 和 SEM 的 PYTHONPATH。
- Noetrium/平台改进：绑定函数应尊重显式 bridge root，并自动为该 root 注入相邻 node_modules；镜像应将 bridge 脚本与依赖打包为不可分离 artifact，doctor 输出最终解析路径。
- 验收：清空外部 NODE_PATH 后，仅调用公开 binding 即能启动真实 bridge；源码安装、wheel 安装和 Docker 安装三种路径均通过同一测试。

### P09：bridge stdout 被第三方协议错误污染

- 现象：Mineflayer/minecraft-protocol 的 PartialReadError 栈写到 stdout，Noetrium JSONL transport 将其当作协议行，报 BRIDGE_INVALID_JSON。
- 根因：stdout 同时承载机器协议和第三方库日志；bridge 创建 bot 时没有关闭协议库错误输出。
- 影响：协议层无法连接，错误看起来像 JSONL/SEM 故障；日志污染可能只在特定 Minecraft 网络包下出现，难以稳定复现。
- 临时处理：在 mineflayer.createBot 选项中加入 hideErrors: true；通过 direct bridge smoke 验证 22/22 行是 JSON object。
- Noetrium/平台改进：stdout 必须是严格协议通道；所有诊断写 stderr 或结构化 diagnostics sink；transport 在 invalid JSON 诊断中保留限长原始行、行号和 stderr tail，但不把日志重新写回 stdout。
- 验收：注入任意 stderr warning 不影响 JSONL；注入 stdout 非 JSON 时能返回稳定错误码、原始行前缀、bridge PID、stderr tail 和日志文件位置。

### P10：reset wrapper 假设主机有 python3.12

- 现象：Minecraft reset wrapper 的 readiness 检查调用 python3.12，node1 主机只有 python3。
- 根因：脚本把容器内 Python 版本假设泄漏到主机 supervisor。
- 影响：服务器已经可用但 readiness 检查失败，pilot 无法开始。
- 临时处理：将该项目专用 wrapper 的 readiness 调用改为 python3；未改动系统 Python。
- Noetrium/平台改进：reset/readiness 逻辑不应依赖未声明的主机解释器；使用 shell/curl/netcat 或由 Noetrium 注入的 runtime helper，并在启动前探测能力。
- 验收：主机仅有 Python 3.x 任意小版本时，隔离 reset 可正常完成；若确实需要 Python，错误中明确显示 required executable 和 found executables。

### P11：root 容器产生 root-owned 结果和归档目录

- 现象：早期 root 容器创建的 world archive/结果目录属于 root，后续普通用户无法写入。
- 根因：实验容器的 UID/GID 没有与宿主运行用户对齐；结果目录和 server archive 的所有权策略没有统一。
- 影响：reset、分析和后处理需要额外权限修复；容易误用全局 chown。
- 临时处理：只针对本项目的 world-archive 和 full result 目录运行精确范围的临时 Docker helper 做 chown 1000:1000；没有删除归档。
- Noetrium/平台改进：默认使用 host UID/GID 映射；容器启动前创建并校验结果目录；在 manifest 中记录 owner；提供 scoped repair 命令，拒绝宽泛路径。
- 验收：普通用户可创建、归档、分析和读取所有本项目产物；任何修复命令都必须显示并确认精确目标目录。

### P12：容器内无法安全读取 host Java PID 的 cwd

- 现象：reset wrapper 为防止误杀其他 Java，检查 /proc/$PID/cwd；Docker 的 /proc/ptrace 限制使容器内即使 root 也无法读取 host PID cwd。
- 根因：容器 PID namespace/host proc 权限与“按 cwd 验证归属”的安全策略不兼容。
- 影响：安全检查在容器内失败；若直接去掉检查又会提高误杀风险。
- 临时处理：先在 host 上核验 PID cwd 与项目 run 目录，确认 PID 为本项目 Minecraft，再只停止该 PID；正式实验容器使用 --pid=host，其 wrapper 只验证自己启动的子 PID。
- Noetrium/平台改进：进程归属验证必须由 host-side supervisor 完成，或由 Noetrium 在创建进程时保存不可伪造的 process generation/lease；不要把 host PID 发现和杀进程责任交给普通环境容器。
- 验收：reset 只能停止拥有匹配 lease、cwd、start marker 的本项目进程；对同端口、同类型但非本项目进程必须拒绝。

### P13：detached/--rm 运行方式导致日志难以追踪

- 现象：早期 pilot 使用 detached 和自动删除容器，出错后容器本身不再保留，不能直接用 docker logs 重建完整上下文。
- 根因：实验生命周期、日志持久化和容器清理策略没有绑定在实验 ID 上。
- 影响：失败诊断只能依赖零散结果文件；重复运行时容易失去 launch 参数。
- 临时处理：后续为每次运行固定容器名、结果目录、full.log、launch-manifest 和 postprocess.log，并保留失败容器状态。
- Noetrium/平台改进：运行命令必须先写 immutable launch manifest，再启动；stdout/stderr、container inspect、exit code 和 failure report 自动归档；--rm 只能作为显式清理阶段。
- 验收：任何失败运行只凭结果目录即可得到 source/image/closure/endpoint/profile/参数/退出原因，不需要依赖容器是否还存在。

### P14：Minecraft agent 行为造成溺水和长时间等待

- 现象：pilot v28 中 ResearchBot 在一个任务中溺水；动作恢复与有界失败机制最终让 pilot 完成，但该任务耗时显著增加，成功率为 0。
- 根因：动作执行器虽有 timeout/recovery，但环境死亡、重生、不可达目标和任务级预算没有统一反馈给 planner/实验控制器。
- 影响：单个坏 assignment 消耗约 20 分钟 pilot 时间；下游看到的是低效失败，而不是明确的环境状态转移。
- 临时处理：依赖现有 action recovery 和 bounded failure，让 assignment 收敛并保存 evidence。
- Noetrium/平台改进：将 death/respawn、stuck、unreachable、budget exhausted 作为结构化环境事件；任务级 deadline 应由 runtime 统一执行；结果中区分 agent failure、environment failure、model failure 和 infrastructure failure。
- 验收：agent 死亡后在固定窗口内产生可验证的 respawn/recovery event；超过预算自动结束 assignment，不拖垮整个矩阵；下游可按失败类别统计。

### P15：qualification closure 在长实验准备过程中失效

- 现象：最初 fresh closure 在 pilot 约 20 分钟后过期；full v1 启动时立即报 runtime qualification receipt is stale。
- 根因：closure TTL 按短期 heartbeat 设计，但完整实验包含构建、pilot、排错和矩阵启动，准备时间已经超过有效期。
- 影响：严格 preflight 正确阻止了不可信运行，但用户必须手工重新生成 closure；正式矩阵启动前才发现过期，浪费准备成本。
- 临时处理：生成并挂载 qualification-node1-20260910-refresh-v2；使用精确 canary 请求重新确认服务。
- Noetrium/平台改进：提供 launch-time qualification status；在预计运行时长超过剩余 TTL 时提前拒绝并给出刷新命令；提供显式 revalidate/refresh workflow，重新执行 live canary，不得伪造 timestamp 或放宽 strict binding；长矩阵支持按 assignment 重新验证并保留 closure generation。
- 验收：启动前显示 valid_until、剩余秒数和预计矩阵时长；不足时不创建容器；refresh 后自动生成新 closure digest 和 manifest；运行中不会静默接受过期 closure。

### P16：第一次 closure refresh 的 canary 请求不够严格

- 现象：refresh 尝试的 canary prompt 没有携带 temperature、max_tokens，Qwen 返回 fenced JSON 或因 finish length 截断，不能作为精确 JSON canary。
- 根因：qualification canary 依赖 prompt 文字，但没有固定采样参数、最大 token 和 thinking 关闭选项。
- 影响：服务本身可能健康，却无法生成可绑定的 qualification evidence。
- 临时处理：v2 canary 固定 temperature=0、max_tokens=32、chat_template_kwargs={"enable_thinking":false}，要求只返回 {"status":"ok"}，并核验 finish_reason=stop。
- Noetrium/平台改进：将 canary request schema 固化为 Noetrium capability；校验 HTTP status、响应 JSON、exact body、finish reason、model identity、request/response digest；错误直接指出缺少的请求字段。
- 验收：任何模型服务只能在 deterministic canary 通过后进入 closure；fenced text、截断、thinking 输出都明确分类为 canary failure。

### P17：模型请求 timeout 会使整个矩阵整体退出

- 现象：full v2 在第一个 assignment 的 UMM 执行中报 ModelEndpointError: model endpoint HTTP transport failed: TimeoutError，最终 SEM UMM assignment failed: NODE_EXECUTION_FAILED，整个容器退出码 1。
- 根因：Noetrium 的模型 endpoint timeout 通过 assignment/runtime 层向上冒泡，矩阵没有将单 assignment 失败转换成可恢复的记录，也没有看到足够的 timeout provenance（请求 ID、deadline、重试次数、服务健康快照）。
- 影响：已有的 partial model request 和结果不能自动进入 assignment-level failed record；完整论文矩阵需要从头重跑，计算成本和时间损失很大。
- 临时处理：保留 full-v2 结果目录和容器日志；没有把失败运行伪装成成功，也没有标记 claim-ready。
- Noetrium/平台改进：统一 request deadline budget；对可重试的连接/读取 timeout 做有界重试和 backoff；assignment 级 checkpoint/resume；失败记录必须含 request digest、endpoint generation、elapsed/deadline、retry history、stderr/health snapshot；只有不可恢复的全局 invariant failure 才终止整个矩阵。
- 验收：单个 assignment 的模型 timeout 会产生可分析的 failed assignment record，并按策略重试/跳过/恢复；矩阵重启可从最近 checkpoint 继续；报告明确区分 partial run 与 claim-ready。

### P18：后处理触发正确，但失败时没有可交付分析

- 现象：postprocess watcher 等待容器退出；v2 退出码为 1 后只记录 full matrix failed; analysis not marked claim-ready，没有生成正式 summary/figures。
- 根因：后处理只对全局 exit code=0 开放，失败运行的 partial evidence 没有单独的 failure report 或诊断汇总。
- 影响：对排障很安全，但论文开发阶段不能快速看到已完成 assignment、失败分布和损失位置。
- 临时处理：保留 raw results、model request blobs、launch manifest 和 logs；不把 partial data 当正式统计。
- Noetrium/平台改进：提供 analyze --partial，输出 non-claim-ready diagnostic summary，列出完成/失败/未开始单元和失败 taxonomy；正式 claim-ready 仍必须由完整性门禁授予。
- 验收：exit=1 也能生成明确标注 claim_ready=false 的诊断报告；不会将 partial 数据混入正式论文统计。

### P19：多层 source/install 路径让错误定位复杂

- 现象：容器内同时存在 /opt/noetrium 源码、venv 的 site-packages、SEM 的 /opt/sem 和外部结果挂载；仅设置 PYTHONPATH=/opt/noetrium 未能覆盖已安装包解析。
- 根因：实验镜像不是单一 source of truth；Python import precedence 和 Node module resolution 分属两套规则。
- 影响：改过的代码、正在运行的代码和 bridge asset 可能不是同一份；诊断容易误判。
- 临时处理：在 launch manifest 中同时记录 Noetrium commit、SEM commit、image digest，并在运行参数中显式写出 PYTHONPATH。
- Noetrium/平台改进：镜像内只保留一个明确 runtime package；doctor 输出 module.__file__、bridge script、node_modules、schema 和 commit；禁止隐式 overlay 覆盖核心包。
- 验收：doctor 能证明每个实际 import 的文件路径；source/image/provenance 不一致时在 preflight 阶段失败。

### P20：旧进程清理存在误杀风险

- 现象：node1 同时运行 Qwen、Minecraft、其他用户 Java/bridge、历史 Docker 容器；不能按端口、进程名或 bridge.js 粗暴清理。
- 根因：系统级资源没有项目 lease；进程名和端口不是可靠所有权证明。
- 影响：错误 kill 会中断别人服务或模型服务，破坏实验和共享服务器。
- 临时处理：只停止精确核对过的 5 个旧项目容器；保留 Qwen、Minecraft 主服务、其他用户 Java、MC-MineEvolve、Firedrake 和无关容器；结果目录不删除。
- Noetrium/平台改进：所有启动资源写入 project-scoped lease，包含 container name/ID、PID、cwd、start marker、argv digest、owner and run ID；清理命令只接受 lease 匹配对象。
- 验收：清理前打印 exact target 和 mismatch reason；没有匹配 lease 时拒绝操作；永远不以“看起来像项目进程”作为停止依据。

## 5. 当前已确认的有效做法

这些做法可以保留为后续自动化的验收基线：

1. 先读取最新设计和 handoff，再决定依赖关系；旧版本规则必须标记为 superseded。
2. GitHub、服务器 checkout、实际镜像、运行时 import 路径四者分别核对，不能只看一个 SHA。
3. Noetrium generic image 与 Minecraft image 明确分开；Minecraft 用 Dockerfile 和 compose overlay。
4. 先跑 runtime doctor、direct bridge smoke、qualification canary，再跑真实 pilot，最后才跑 full matrix。
5. bridge stdout 只允许 JSONL；第三方日志进入 stderr。
6. 每个运行固定 result directory、container name、launch manifest、full.log、postprocess.log。
7. 所有清理操作只针对精确项目对象；不删除历史 world archive 和 partial results。
8. qualification 过期就重新生成，不伪造时间、不绕过 digest/heartbeat/canary 检查。
9. pilot 或 partial matrix 只能标记 pilot_not_claim_ready / claim_ready=false，不能直接支持论文 claim。

## 6. 下一阶段 Noetrium 深度优化规格

本节不是本轮代码改动，而是由上述问题归纳出的实施要求。

### 6.1 一条下游命令的目标工作流

建议提供类似以下的公开流程：

~~~text
noetrium experiment prepare \
  --environment minecraft \
  --model-profile sem-qwen38-27b \
  --plan paper-full \
  --results-dir /data1/.../results/run-id
~~~

prepare 必须完成：

- 检查 source tree dirty 状态、Python/Node/Java、依赖版本和 image capability；
- 自动选择 generic 或 Minecraft image；
- 解析实际 Python bridge 与 Node module root；
- 检查 server lease、端口和 reset 能力；
- 计算预计运行时间与 qualification 剩余 TTL；
- 执行确定性的 model canary；
- 生成 immutable launch manifest；
- 所有失败在容器启动前退出。

之后：

~~~text
noetrium experiment run --manifest /data1/.../launch-manifest.json
noetrium experiment status --run-id <run-id>
noetrium experiment analyze --run-id <run-id> --partial
~~~

正式结果必须经过完整性门禁后才可输出 claim_ready=true。

### 6.2 优先级排序

| 优先级 | 改进 | 直接解决 |
|---|---|---|
| P0 | bridge root 与 node_modules 自动解析；stdout/stderr 严格分流 | P08、P09、P19 |
| P0 | runtime doctor + image capability manifest | P04、P05、P06、P07 |
| P0 | qualification prepare/refresh/status，保留 strict binding | P15、P16 |
| P0 | request deadline、结构化 timeout、assignment checkpoint/resume | P17、P18 |
| P1 | host-side process lease 与安全 reset supervisor | P11、P12、P20 |
| P1 | 统一 UID/GID 与 scoped artifact repair | P11、P13 |
| P1 | death/respawn/stuck/budget 事件和失败分类 | P14 |
| P1 | source/install provenance 自检 | P02、P03、P19 |
| P2 | Git 通道能力探测和本地/远端提交一致性报告 | P01、P03 |

### 6.3 必须新增的自动化测试

- wheel 安装、源码运行、Docker 运行三种模式下，公开 Minecraft binding 都能找到同一 bridge 和依赖；
- 自定义 MC_BRIDGE_DIR 时自动推导相邻 node_modules，无手工 NODE_PATH 也能启动；
- bridge stderr 任意输出不污染 stdout JSONL；
- stdout 非 JSON 时错误包含稳定 cause code、限长 raw line、line metadata 和 stderr tail；
- Python/Node/Java 版本不满足时 preflight 在实验前失败；
- generic image 请求 Minecraft 时在 preflight 失败并提示 MC overlay；
- qualification TTL 不足以覆盖预计矩阵时长时提前失败；
- deterministic canary 拒绝 fenced JSON、截断响应、错误 model 和 thinking 输出；
- request timeout 经过有界 retry 后写 assignment failure/checkpoint，矩阵可 resume；
- reset 只能操作匹配 project lease 的进程；
- 普通用户可以完整写入结果和 world archive；
- partial analyze 输出 claim_ready=false，正式分析绝不吸收未完成 assignment。

## 7. 安全与边界声明

- 本轮没有停止或重启 Qwen 服务、无关 Minecraft 服务、其他用户 Java/bridge 或其他 Docker 容器。
- 本轮没有删除历史结果、world archive、partial request blob 或异常文件。
- 所有对权限的修复都限制在本项目的明确结果/归档目录。
- 没有使用过期 closure 伪造成功，也没有把 pilot 当作论文 claim。
- full v2 使用的 image、Noetrium commit、SEM commit、closure digest 已写入 launch manifest；该运行失败事实必须保留，不能用后续优化后的成功运行覆盖历史。
- 本文不包含 RCON 密码、模型 API key、SSH 私钥或其他可直接复用的秘密。

## 8. 本轮结束时的待办

1. 保存并 commit 本文档；本轮只 commit，不 push。
2. 保留 full-v2 失败运行及其 raw artifacts，后续先做 partial diagnostic。
3. 下一轮按 P0 顺序实现 Noetrium 的 bridge/module resolution、doctor、qualification lifecycle 和 model timeout/resume。
4. 每项优化单独增加回归测试，并用新 image digest 运行新的 full matrix。
5. 只有新的 full matrix 完整通过、分析门禁给出 claim_ready=true，才进入论文最终表格和 claim 撰写。

