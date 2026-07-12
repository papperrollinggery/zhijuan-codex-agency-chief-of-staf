# Agency Chief of Staff for Codex

一个结果负责型 Codex 幕僚长 Skill：把复杂任务从目标澄清推进到研究、规划、执行、验证、独立审核和最终交付。

它不靠堆角色或 receipt 证明自己工作，也不向 `AGENTS.md` 注入路由。主线程对结果负责；原生 subagents、Goal、真实 task/thread/worktree 都按任务需要使用。

## 适用场景

- 明确调用 canonical 入口 `$agency-chief-of-staff`。
- 要求“幕僚长 / Codex Agency / 完整团队”负责复杂任务闭环。
- 要求先研究，再规划、执行、验证和审核。
- 长任务需要 Goal、checkpoint 和停止条件。
- 需要并行探索、实现或独立 cold review。
- 需要 release readiness、Skill hardening、多文件可靠性或客户交付质量审核。
- 明确要求真实 Codex task/thread、隔离 worktree、thread id、receipt 或 cleanup 证明。

普通小问题不应触发本 Skill，除非用户显式调用。

## 核心工作流

```text
目标与完成标准
  → 当前事实研究
  → 最小计划
  → 主线程执行 + 按收益委派
  → 真实验证
  → 独立 cold review
  → 修复与复验
  → 简洁交付
```

关键设计：

- 主线程是 outcome owner，可以直接研究、编辑、测试、整合和交付。
- 动态使用 1–3 个边界清晰的 subagent，不维护固定 16 角色组织。
- Goal 只用于明确的长期目标，不为短任务生成 Goal Ledger。
- 真实 task/thread 只在用户明确要求真实独立执行面时使用。
- 只有机器审计确实需要时才输出结构化 receipt。
- 默认一次 cold review 加一次修复后的定向复核，避免无限 review wave。
- 宿主要求先公告 Skill 时，启动前最多允许“使用公告 + 一次路径恢复”；成功读取正确 bundle 后立即输出 `COS_BOOT_RECEIPT`，此前不得碰业务文件或调用协作工具。
- Worker bypass 只接受首行为 `AGENCY_WORKER: true`、标签有序且各出现一次、六个字段均非空的 packet；字段可使用非空多行块。

## 不依赖 AGENTS.md

激活路径只有：

1. 显式 canonical 调用 `$agency-chief-of-staff`；
2. canonical frontmatter `description` 的宿主隐式匹配；
3. `agents/openai.yaml` 中的 UI metadata 和 default prompt；
4. 仅为旧调用保留的显式兼容入口 `$zhijuan-codex-agency-chief-of-staf`。

隐式发现是宿主的 best-effort 行为，受当前 skill context budget、已安装 Skill 数量和宿主选择策略影响，不是可依赖的保证。需要确定启动时，请显式使用 `$agency-chief-of-staff`。旧 slug 关闭隐式调用；同一请求同时出现两个 slug 时，只执行 canonical 入口。

安装器不会读取、创建、追加或修改项目/全局 `AGENTS.md`，也不提供 routing 注入参数。已有 `AGENTS.md` 仍作为项目规则正常生效，但不是本 Skill 的安装或激活机制。不要通过向 `AGENTS.md` 注入路由文本来补偿宿主的 context budget 限制。

## 安装

当前安装器支持 macOS 和 Linux，要求 Python 3.10+。它依赖 POSIX `fcntl` advisory lock 与安全的 `O_NOFOLLOW` 文件打开；缺少这些能力的平台会 fail closed，不会降级为无锁安装。当前不承诺 Windows 支持。

```bash
python3 scripts/install_skill.py
```

默认作为一个交易安装两个 manifest-matched runtime bundle：

```text
~/.agents/skills/agency-chief-of-staff
~/.agents/skills/zhijuan-codex-agency-chief-of-staf
```

第一个是 canonical bundle，支持显式调用和宿主 best-effort 隐式发现。第二个是安装器从同一源确定性生成的 explicit-only 兼容 bundle，仅保留旧 `$zhijuan-codex-agency-chief-of-staf` 调用，不是第二份维护源。

覆盖不同版本：

```bash
python3 scripts/install_skill.py --force
```

安装器只复制运行时 allowlist，并在同一 OS advisory lock 下冻结双 bundle 源 manifest、检查当前 pair、staging、promotion 和最终 pair 校验；进程退出或崩溃会由 OS 释放锁。每次把 bundle 判为 `current` 前还会执行独立于内容 revision 的 `sealed-tree-v1` 检查：根目录必须是当前用户拥有的 `0700` 真目录，四个允许的子目录必须精确为 `0755`，九个运行时文件必须精确为普通文件、规范 `0644/0755`、单硬链接且归当前用户所有；额外文件/空目录、bundle 内部 symlink、FIFO、socket、device、宽权限或 hardlink 都会成为 `different`，不能通过内容 hash 伪装成 current，`--force` 可整体替换这类真实目录污染。若 bundle 根本身是 symlink，安装器会无条件拒绝并要求人工确认，而不会跟随或自动替换。安装器在创建锁和任何暂存前拒绝源码与 target root/任一 target 相等或互为祖先。这能串行化所有遵守同一锁的安装器，但不声称抵抗非协作的同用户写者，也不声称 crash-atomic visibility。事务失败会回滚已接管的目标，不会把 GitHub workflow、历史 validation、README 或仓库管理文件打进运行时 Skill。

JSON receipt 中的 `package_source_revision_sha256` 是 canonical 与 legacy 两份期望 manifest 组成的完整对象经 key-sorted compact canonical JSON 编码后的 SHA-256。两个 bundle 共享同一个 revision；任一 bundle 内容变化都会改变它，输入字典顺序不会。它只是内容指纹，不是 Git tag、语义版本、发布签名或供应链身份认证。

`--force` 会整体替换这两个受管 bundle，因此正常完成时也会移除旧版本 bundle 内部遗留的 `AGENTS.md` / `AGENTS.override.md`；它仍不会读取或改动项目级、用户全局的 `AGENTS.md`。已验证的新 pair 一旦提交，后续 transaction cleanup 失败不会伪装成成功清理：JSON 会返回 `cleanup_complete=false`、`cleanup_warnings`、`residual_paths` 和 `cleanup_guidance`。任何使用保留前缀 `.<slug>.backup-`、`.<slug>.staging-` 或 `.<slug>.failed-` 的路径都持续阻塞，即使后缀为空、不是 UUID 或看起来不是本安装器生成的值。

## 使用

最短调用：

```text
使用 $agency-chief-of-staff 把这个任务做到可验证完成。
```

长期目标：

```text
使用 $agency-chief-of-staff。为这个迁移设定 Goal，先研究现状，再规划、执行、验证和独立审核，直到满足停止条件。
```

真实线程：

```text
使用 $agency-chief-of-staff。创建真实隔离 worktree task 完成实现，返回真实 id、产物、验证、adoption 和 cleanup；工具不可用时明确 TOOL_BLOCKED。
```

旧自动化或历史 prompt 可继续显式调用 `$zhijuan-codex-agency-chief-of-staf`，新集成应使用 canonical slug。

## 当前模型能力的使用方式

本次架构按当前 Codex 能力设计：复杂主任务保留高能力模型，独立的只读探索/测试可在实测收益明确时交给成本更低的 worker，安全与 cold review 使用较高 reasoning；只有真正可并行的工作才派发。按官方 latest-model 指南，在当前账户和宿主可用时，高难度 agent 可从 `gpt-5.6`（即 Sol）起步，并按质量/成本权衡评估 `gpt-5.6-terra`；GPT-5.6 的 reasoning effort 是 `none`、`low`、`medium`、`high`、`xhigh`、`max`，Codex Ultra 是协作模式，不是 reasoning effort。Skill 本体不固定模型 slug，避免模型更新后失效；具体“已验证模型”只以当次 model-smoke receipt 为准，model-agnostic design 不等于已在最新模型上验证。

相关官方说明：

- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
- [Long-running work](https://learn.chatgpt.com/docs/long-running-work)
- [Latest model guidance](https://developers.openai.com/api/docs/guides/latest-model)

## 验证层级

验证名称必须诚实区分：

1. `package/contract`：离线检查 frontmatter、runtime manifest、引用、场景 schema 和安装行为；不声称证明模型行为。
2. `model-smoke`：从已验证的全局双 bundle 冻结一份 clean-HOME 安装快照，在无 `AGENTS.md` routing、禁用 plugins/apps、环境变量 `inherit=none` 的临时仓库里真实调用当前 Codex 模型；子集运行只会得到 `passed_partial`。
3. `threadops-smoke`：只有发布目标明确要求真实 task/thread 证明时，使用 Codex Desktop 工具核验真实 id、readback、worktree 和 cleanup。

运行离线质量门：

```bash
/bin/bash -p scripts/quality_gate.sh .
```

运行真实模型前测前，必须同时准备：经审查的原生 Codex 平台二进制绝对路径、显式模型 id、该模型支持的显式 reasoning effort，以及标记为 `dedicated` 或 `primary` 的 auth。`dedicated` 标签和未验签 JWT payload 只产生声明级诊断，不证明低权限或隔离。被测 Skill、case 和 Codex 进程同属当前 OS 用户，临时 `auth.json` 理论上可被恶意被测内容读取；环境变量最小化、显式工具 PATH、文件前后不变和 exact-value 输出扫描都不是秘密边界。对不可信 PR，必须放进一次性 OS 用户或容器，不能使用主账号凭据。

```bash
export CODEX_NATIVE_EXECUTABLE=/absolute/path/to/native/codex-binary
export CODEX_EVAL_MODEL=gpt-5.6-sol
export CODEX_EVAL_REASONING_EFFORT=max
export CODEX_EVAL_AUTH_JSON=/path/to/eval-auth.json
export CODEX_EVAL_AUTH_CLASS=primary
export CODEX_EVAL_SOURCE_TRUST=reviewed
```

`CODEX_NATIVE_EXECUTABLE` 必须直指可执行的 Mach-O、ELF 或 PE 二进制。不要盲目使用 `command -v codex` 的结果：shell/Node/provider wrapper 或 symlink 会被拒绝。macOS RC 证据还要求 Apple `codesign` 验证 OpenAI Team ID `2DC432GLL2` 的主 binary 与 `codex-code-mode-host`；runner 执行验签后冻结的私有副本，并对源文件、副本、版本和签名做前后复验。其他平台在没有等价 publisher attestation 前 fail closed。模型/provider/effort 是否被采用，只接受由 exec `thread_id` 唯一绑定的临时 rollout 中 `session_meta` / `turn_context` 白名单字段；stderr、agent 文本和 `codex exec --json` 自由字段永远不算证明。

上例是本机单案例已经观测到的 `gpt-5.6-sol/max` 组合，不代表其他账户可用，也不代表当前 HEAD 已有全量发布收据。本候选仍必须对最终 runner/case/runtime hash 重跑 20/20；历史或中间 probe 不能替代。Runner 会把 model unavailable、client incompatible、timeout 和 usage limit 分开分类为外部未决，suite 与发布仍 fail closed。它使用 `--ignore-user-config`，必须通过 `--reasoning-effort` 重新显式绑定，并在同一命令中启用 `multi_agent`。

不要仅凭模型“最新”或更高 effort 就假定协作证据成立。`codex exec --json` 目前会丢失部分 spawn/receiver 细节，因此 runner 同时核对隔离 `CODEX_HOME` 中的主 rollout 与 child rollout。严格 reviewer case 只接受一个 reviewer：真实 `spawn_agent` 返回路径、同 child 的 started activity、主线程 id/agent path/source/depth/cwd 绑定，以及与主执行完全一致的 OpenAI provider、model、effort 和 CLI。child rollout 中父线程送入的 `response_item.type=agent_message` 是入站 task transport，不是 child 输出；runner 要求它恰好一次、使用当前 parent/child path 与 child turn，且可见部分精确等于当前 `Message Type: NEW_TASK` / `Task name` / `Sender` / `Payload` 头，再带受限 encrypted envelope。加密形状只提供语法绑定，不是认证；它必须是 turn 后第一个 child response item，入站前的事件/输出、入站后的未知 action，或缺失、重复、畸形、错 turn、错 author/recipient、晚到 follow-up 都会 fail closed。默认 reviewer packet 不含任何 `$slug`，也不要求 guard read，避免 worker 递归启动主流程；只有宿主在 worker 开始前已自行强制加载 bundle 时，才允许那一次被动 guard read，其绝对路径、受限参数和完整原始输出必须与冻结安装一致。reviewer 的 child turn 随后只允许唯一 artifact 调用及其匹配输出；code-mode wrapper 的完整参数对象必须是受限字面量，artifact 命令必须为 `/bin/cat <artifact>`，原始输出精确匹配最终文件，且读取时间晚于文件最后修改。其唯一同-turn `task_complete` 必须由宿主按 author/recipient 投递；投递必须完整等于当前 `Message Type: FINAL_ANSWER` / `Task name` / `Sender` / `Payload` envelope，且 payload 与 child terminal 精确一致，并发生在 child terminal 之后、主线程唯一 task-complete/持久化 final 之前。wait 只用于终态尚未投递时阻塞，其 call/output 也必须绑定 `namespace=collaboration` 与当前主 turn；wait 不是 reviewer 身份或完成证据。收到任何非空 reviewer terminal 后不得用 follow-up/send 开启第二 turn；schema 不合格就保持审核未验证。每次运行的 marker 随机生成，不存在于源码或顶层用例 prompt；reviewer packet 的`期望产物`只描述证据类型与终态 schema，不得预填目标行、marker、artifact 原文或其他本应直接读回的答案。持久化前 marker 会被替换；若宿主只保存不透明的 spawn prompt，receipt 会明确把 prompt 内容、自包含性和 marker 未转发标为未验证，opaque token 本身不贡献可信度。RC 只依赖 reviewer 对修改后产物的唯一直接读回、身份/终态/投递绑定与主线程采纳；这不足以支持 stable cold-review 声明。提前声称 reviewer 完成、中间 PASS、除已验证 guard 外的额外工具、表达式、子串包裹、解码命令、普通 wait 或最终纠正后的旧 PASS 都不算证据。无阻塞 reviewer 终态必须严格等于四行机器 schema：实际第一行、完整目标行、`REVIEW_FINDINGS_COUNT: 0`、`REVIEW_VERDICT: NO_BLOCKING_FINDINGS`；主线程 final 必须严格等于该四行加 `MAIN_REVIEW_ADOPTION: ACCEPTED` 与 `COLD_CONTEXT_ISOLATION: UNVERIFIED`。任何额外文本、重复或矛盾都会关闭 RC。另一个自然 full-cycle case 的 packet 同样不携带目标答案，并要求 reviewer 直接读取当前文件，但 oracle 不规定或认证其 artifact 工具序列；它只要求最终 artifact 的 `max(mtime, ctime)` 严格早于 spawn、唯一 child 终态严格等于实际读回的 `NATURAL_REVIEW_FILE` / `NATURAL_REVIEW_TARGET` / `REVIEW_VERDICT` 三行，并由宿主精确投递。主线程 final 必须严格等于这三行加 `MAIN_REVIEW_ADOPTION: ACCEPTED`、`COLD_CONTEXT_ISOLATION: UNVERIFIED`、`reviewer-owned read 未验证`，不得有其他文字。即使 rollout 出现工具 trace，该自然 case 仍固定报告 `reviewer_owned_read_verified=false`、`context_isolation_verified_count=0`，不能单独当作产物读回或 cold review 证据。receipt 只保留计数、布尔值和哈希，不复制 prompt、回复、cwd 或 thread id。已验证 cold review 还要求可证明的上下文隔离和 marker 未转发；仅请求 `fork_turns:none` 不足。

两条协作 oracle 还会绑定当前宿主的 `namespace=collaboration`、call/output/response `turn_id`、started `event_id` 与 250ms 内的宿主时间，以及 `fork_turns:none` child 的冗余 session 身份；这些字段只能证明同一宿主 lifecycle，不能升级为上下文隔离。严格链还要求 started 记录位于 spawn call/output 之间，唯一产物读取不早于 started。产物时序按 `max(mtime, ctime)` 严格比较，防止回拨 mtime。受审 case 把启动行绑定为完整固定文本；除规范预读公告、该启动行、精确 final 和按序且不重复的 `MAIN_PROGRESS:*` 白名单外，任何主线程 assistant 文本都会关闭证据。严格 reviewer 最多允许一次精确 `REVIEW_PROGRESS: READING_ARTIFACT`：若存在被动 guard，必须在匹配 guard output 之后、artifact 调用之前；无 guard 时也必须在入站 transport 之后。自然 reviewer 最多允许一次精确 `REVIEW_PROGRESS: CHECKING_ARTIFACT`。在隔离、无 memory 的 release eval 中，main/child 的 rollout response 与 raw event，以及公开 exec JSON，每条表面都必须各有且仅有一个精确终态；跨表面镜像不合并计数，表面缺失或出现额外、重复、跨 phase、跨 turn、错序、回填时间或畸形文本都会失败。Rollout assistant/delivery 分别要求单一 `output_text` / `input_text`，raw event 锁定当前四字段 schema 且要求 `memory_citation=null`。主 task-complete 必须是 rollout 最后一条。这样无需依赖开放式同义词分类来判断中间 RCE/P0/拒绝/读取/隔离声明；任何非规范消息、畸形/重复投递或投递后反转都 fail closed。

运行全量真实模型前测：

先用 `python3 scripts/install_skill.py --force` 将当前 checkout 的 canonical/legacy 双 bundle 同步到全局安装目录；runner 会在冻结前后同时拒绝与当前源 manifest 不一致或不满足 `sealed-tree-v1` 的安装。RC eligibility 也绑定这个树完整性结果，不能只靠内容 hash 或启动时的一次检查。

```bash
/bin/bash -p scripts/model_smoke.sh \
  --root . \
  --out validation/current/model-smoke-$(/bin/date +%Y%m%d-%H%M%S) \
  --codex-executable "$CODEX_NATIVE_EXECUTABLE" \
  --model "$CODEX_EVAL_MODEL" \
  --reasoning-effort "$CODEX_EVAL_REASONING_EFFORT" \
  --skill-source verified-installed-snapshot \
  --source-trust reviewed \
  --auth-json "$CODEX_EVAL_AUTH_JSON" \
  --auth-credential-class "$CODEX_EVAL_AUTH_CLASS" \
  --acknowledge-auth-readable-to-eval-process \
  --require-release-tier rc
```

Runner 只允许 `read-only` / `workspace-write`，拒绝危险 sandbox、越界 case id/artifact 路径、既有输出目录和 symlink；全部 25 个行为 case 都以完整 canonical JSON 指纹锁定，其中 20 个是必跑 model-smoke，并加入四个首行 marker 后字段缺失、重复、乱序或空值的 worker-bypass 负例、一个不微操 reviewer 工具协议的自然协作完成/采纳案例，以及普通 focused code fix / code review 负例。读取前公告固定为一个无业务内容的 canonical/legacy 模板；入口 load 只有在 boot 前由一个稳定工具尝试完整读取所选 bundle，且聚合输出精确匹配时成立，boot 后可按任务再次读取同一 bundle，另一入口始终禁止。`verified-installed-snapshot` 在运行前后以稳定的 `lstat`/nofollow 双扫描验证真实全局双 bundle 的精确节点集合、type、规范 mode、owner、文件 link count、内容与所有保留事务前缀，把仅这两个 sealed bundle 冻结到每 case 的 clean HOME，并再次验证冻结副本；全局 pair 或每 case 副本的任何树漂移都会关闭 RC。影响这些结论的实际 `scripts/install_skill.py` 与 runner、行为 case、runtime manifest 一样在运行前冻结 bytes、运行后复核，并以 `installer_sha256` 写入收据；helper 漂移会把状态降为 failed。project parent 与 HOME/CODEX_HOME 放在不同私有子树；这降低 `find ..` 枚举风险，但不是 OS 隔离。Runner 在启动模型前记录 CODEX_HOME 根 inode，结束后从同一 root/sessions dirfd 逐层使用 `O_DIRECTORY` / `O_NOFOLLOW` 做两次有界扫描；每轮都比较目录前后状态与首末枚举、文件 fd 与父目录名称绑定，两轮 bytes 和 metadata manifest 必须完全一致，随后再复核根路径与 `sessions` 名称。它证明扫描区间内得到自洽稳定快照，不证明最终校验之后不存在同用户 future writer；identity、review 与 auth 只消费这份已验证 bytes。全部 raw rollout 同时做 raw/JSON 解码后的 exact-auth 扫描；任一泄漏、根替换、目录交换、同名 rebind、late add/remove、特殊文件、总量超限、malformed/non-object JSONL 或扫描失败都会关闭 RC。写入案例显式列出 tracked、untracked 与 ignored 路径，隔离 system/global Git 配置，并用专用双扫描 manifest 覆盖 `.git` 下所有文件和目录，包括 `__pycache__`、空目录、mode/uid/gid、inode、ctime/mtime 与内容哈希。Runner 还要求零 CLI-owned context-budget overflow、零 snapshot 漂移和零 `AGENTS.md` routing。每个 case 的主 rollout必须恰有一条 `session_meta` 和一条 `turn_context`，只持久化与请求完全相符的 model/provider/effort/CLI/source；异常值只产生固定错误，不写入收据。timeout 会收敛本次 POSIX process group，但不声称约束主动 `setsid` 逃逸。最终收据经私有 staging 原子提升。

V2 收据把发布证据拆成两轴：`artifact_rc_evidence_eligible` 只证明 20 个受审 smoke 覆盖的路由、自然协作完成/投递/采纳、独立的严格产物读回 reviewer chain、rollout 身份、官方签名执行面、安装快照/私有目录分离与清理；它不证明原生 Goal 生命周期、真实 Codex task/thread ThreadOps、cold-context isolation 或宿主 plugins/apps 兼容性，这些继续列在 `untested_capabilities`。`credential_rc_handling_verified` 只证明本次隔离 auth 文件未变、全部 raw rollout 扫描成功且输出未出现 exact auth 值。primary 可用于经审核源码的 RC，但 `operational_credential_safety.verified` 仍为 `false`，不能声称低权限、专用或 OS/container 隔离。`--require-release-tier rc|stable` 会机械拒绝不满足的收据；`prerelease` 仅为 `rc` 兼容别名。当前 receipt 明确写入 `stable_supported=false`：stable 仍需要上下文隔离证据、权威 workload identity 和其余未测试能力，现阶段不可满足。这些门禁是本项目自设证据政策，不是 OpenAI 官方认证。

发布前轻量安装复核：

```bash
/bin/bash -p scripts/release_smoke.sh .
```

v0.1.x 的旧 validation receipts 保留在 Git 历史和对应 tag 中，不进入当前 checkout 的 release gate，也不代表当前 HEAD 已验证。

## 运行时结构

```text
SKILL.md
agents/openai.yaml
references/
  real-threads.md
  delivery-review.md
  long-running-work.md
  history-audit.md
assets/
  WORK_RECEIPT_TEMPLATE.yaml
  DELIVERY_EVIDENCE_TEMPLATE.yaml
scripts/
  audit_historical_threads.py
```

兼容说明：拼写正确的 `agency-chief-of-staff` 是唯一 canonical slug；含 `staf` 的旧 slug 只作 explicit-only 兼容入口，避免破坏现有显式调用。
