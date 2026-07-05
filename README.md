# Zhijuan Codex Agency Chief of Staff

Dynamic Chief-of-Staff Agency workflow for Codex.

This skill helps Codex decide whether a request should be handled directly, planned first, tracked as a long-running goal, delegated to real Codex Threads, reviewed independently, rescued, or turned into a reusable improvement. It is designed for users who want a high-autonomy Codex workflow without losing evidence, receipts, or cleanup discipline.

## 中文快速说明

这个 Skill 的目标不是“多开几个角色”，而是把复杂任务变成可验证、可收敛、可归档的 Codex 工作流。显式调用后，它要求当前线程先输出 `COS_BOOT_RECEIPT`，再判断任务复杂度、是否需要 Plan/Goal、是否需要真实 Codex Threads、如何派发 worker、如何收集 receipt、如何做独立审查和 cleanup。

用户可见输出默认中文、简洁、先结论。`COS_BOOT_RECEIPT` 作为自动化识别标记保留，但 T0/T1、状态说明、轻量答复、用户只是问“为什么/什么情况/是否受阻/怎么显示”时，必须用中文短句，例如：`COS_BOOT_RECEIPT：已启动；复杂度 T0；不派发；原因：状态说明。` 只有真实派发、阻断、heartbeat 验收、release receipt、失败诊断或用户明确要求机器字段时，才展开完整机器字段。

适合使用的场景：

- 你要求“幕僚长 / Codex Agency / 完整团队 / 真实 Codex Threads / worker thread / receipt / cleanup”。
- 任务需要多个角色协作，例如规划、研究、实现、创意、分镜、提案、资料整理、文案、故事、执行计划、反驳审核。
- 你要检查线程是否真的执行、是否卡住、是否没有归档、是否把测试 PASS 误当成客户交付质量。
- 你要把某个长期复用 Skill 或公开仓库做成可发布版本，并需要 release receipt、cold review、rebuttal review、安装验证和历史失败审计。

关键边界：

- 安装 Skill 只让它可被选择；默认不会写入 `AGENTS.md`，也不能强制所有未来任务自动进入幕僚长流程。
- 如果希望某个项目默认路由到幕僚长流程，需要把 [references/AGENTS_ROUTING_SNIPPET.md](references/AGENTS_ROUTING_SNIPPET.md) 合入该项目 `AGENTS.md`，或运行 `python3 scripts/install_skill.py --agents-routing project --project-root /path/to/project`。
- 当用户明确要求真实线程时，必须输出真实 `THREAD_DISPATCH_RECEIPT`；没有真实线程工具时只能 `TOOL_BLOCKED`，不能用同线程角色扮演替代。
- 创意、分镜、提案、资料整理、文案、故事、执行规划等客户交付物，不能只凭 worker receipt、脚本 PASS 或 `VALIDATION=PASS` 宣称 `client-ready` / `可交付`；必须有 `DOMAIN_DELIVERABLE_RECEIPT`。

## Why Use It

- Classifies tasks from T0 to T5 instead of forcing every request into the same process.
- Keeps light tasks light: no unnecessary Task Graphs, teams, or packets.
- Uses Plan and Goal mode only when the task benefits from them.
- Routes work to Skills, Agents, or Codex Threads with explicit scope and receipts.
- Treats Codex Threads as a real execution surface, not a synonym for subagents.
- Emits `COS_BOOT_RECEIPT` first when explicitly invoked, so a run cannot silently skip the Chief-of-Staff startup.
- Treats stuck threads as recoverable failures through bounded rescue.
- Enforces release review convergence budgets and a single release receipt table.
- Requires `DOMAIN_DELIVERABLE_RECEIPT` before creative, storyboard, proposal, research, copy, story, execution, or planning outputs can be called client-ready.
- Ships with local validation, pilot harness, and release smoke checks.

## Install

From this repository:

```bash
python3 scripts/install_skill.py
```

Requires Python 3.10 or newer. CI currently runs the quality gate on Python 3.10, 3.11, and 3.12.

The default target is:

```text
~/.agents/skills/zhijuan-codex-agency-chief-of-staf
```

To overwrite an existing different install:

```bash
python3 scripts/install_skill.py --force
```

Installation makes the Skill discoverable; it does not force every future Codex thread to become a Chief-of-Staff thread. Use one of these activation paths:

- Explicit prompt: `使用 $zhijuan-codex-agency-chief-of-staf`.
- Project default: copy [references/AGENTS_ROUTING_SNIPPET.md](references/AGENTS_ROUTING_SNIPPET.md) into that project's `AGENTS.md`.
- Global default: copy the same snippet into `~/.codex/AGENTS.md` when you intentionally want this routing everywhere.

The installer can add that routing snippet when explicitly requested:

```bash
python3 scripts/install_skill.py --agents-routing project --project-root /path/to/project
```

```bash
python3 scripts/install_skill.py --agents-routing global
```

Use `--agents-routing both` only when you intentionally want both project-local and global routing. The default `python3 scripts/install_skill.py` does not modify `AGENTS.md`.

To install project-local Codex agents:

```bash
bash scripts/install_codex_agents.sh project
```

Do not install user-scope agents unless you intentionally want them in `~/.codex/agents`:

```bash
bash scripts/install_codex_agents.sh user
```

## Use

Minimal prompt:

```text
使用 $zhijuan-codex-agency-chief-of-staf
```

Expected first visible marker:

```yaml
COS_BOOT_RECEIPT:
  skill_loaded: true
  trigger_type: explicit
  thread_role: COS
```

If you want natural-language prompts like “启动幕僚长 / 完整团队 / 真实 Codex Threads” to trigger automatically, keep `agents/openai.yaml` with `policy.allow_implicit_invocation: true` and use the routing snippet in [references/AGENTS_ROUTING_SNIPPET.md](references/AGENTS_ROUTING_SNIPPET.md) for projects where this workflow should be the default.

That routing snippet also carries the Chinese-first visible-output rule, so project-level COS starts stay readable while preserving machine receipts for thread and release evidence.

Realistic prompts:

```text
使用 $zhijuan-codex-agency-chief-of-staf。这个项目我想正式用起来，但不知道差什么，你帮我判断并只做必要修复。
```

```text
使用 $zhijuan-codex-agency-chief-of-staf。我要长期推进一个代码迁移项目，请建立目标、线程分工、验证和救援机制。
```

```text
使用 $zhijuan-codex-agency-chief-of-staf。这个 worker thread 一直没有 receipt，请接管，保留已验证证据，只补失败项。
```

More prompts are in [examples/real-world-prompts.md](examples/real-world-prompts.md).

## Activation Reliability

Codex skills are loaded on demand. Before Codex selects a skill, it mainly sees the skill name, description, path, and optional metadata. For this Skill, that means:

- Skill 描述只能提高选择概率；只有项目级 `AGENTS.md` 或全局 `~/.codex/AGENTS.md` routing snippet can make Chief-of-Staff routing part of the instruction chain before task work begins.
- `agents/openai.yaml` must not disable implicit invocation if you expect natural-language triggers.
- Explicit `$zhijuan-codex-agency-chief-of-staf` runs must start with `COS_BOOT_RECEIPT`.
- Explicit requests for real Codex Threads, worker threads, a complete team, thread id, receipt, or cleanup must dispatch real threads with `THREAD_DISPATCH_RECEIPT` or return `TOOL_BLOCKED`; they must not fall back to same-thread simulation.
- Pre-release quality, public release, multi-file reliability, asset/stale-file/browser-evidence/customer-language audits are T3+ routing cases. They should dispatch real workers or report `TOOL_BLOCKED`, not collapse to `no_dispatch`.
- Every worker Result Packet, Review Packet, or named `*_RECEIPT` must include that worker's own real Codex `thread_id`. A receipt that copies `source_thread_id`, the main thread id, or a historical thread id is `invalid_worker_thread_id` and can only be used as an untrusted clue.
- Dispatch prompts should include the worker's actual id after creation: `你的真实 thread_id 是 <worker_thread_id>` and `receipt.thread_id 必须等于 <worker_thread_id>`. The dispatch receipt records this as `worker_prompt_identity_contract: included`.
- If a Codex worker thread shows "当前工作目录缺失" / "current working directory missing", treat it as stale evidence: record `thread_cwd_missing`, `thread_not_converged`, `adoption_status: rejected_evidence`, and `cleanup_status: archived | cleanup_blocked`; do not continue that thread in place.
- Codex automation heartbeats execute their configured prompt. They only start this Skill when the prompt explicitly invokes `$zhijuan-codex-agency-chief-of-staf` or the target context has the AGENTS routing shim; a heartbeat prompt that says "do nothing else" should never emit `COS_BOOT_RECEIPT`.
- Heartbeat/Automation enablement claims are invalid without activation evidence: cite the `automation_prompt` text/path plus `prompt_contains_skill_invocation: true`, or cite explicit `agents_routing_evidence` / `AGENTS routing shim`. A bare `AGENTS.md` mention is not evidence, and [assets/HEARTBEAT_PROMPT.md](assets/HEARTBEAT_PROMPT.md) by itself does not enable COS heartbeat.
- Heartbeat/Automation enablement claims must also verify the target context: record `target_thread_id`, `target_thread_verified: true`, and at least one readback field such as `target_thread_title` or `target_thread_cwd`. A heartbeat pointed at an unrelated historical thread is a misconfigured automation even if its prompt invokes this Skill.
- Automation enablement is not proof that a heartbeat advanced work. Every T4/T5 heartbeat run must emit `HEARTBEAT_RUN_RECEIPT` or `COS_HEARTBEAT_RUN_RECEIPT` with target readback, due status, `dispatch_required`, `dispatch_outcome`, `THREAD_DISPATCH_RECEIPT` or `TOOL_BLOCKED`, stuck/rescue decision, and `next_due_or_next_check`; if dispatch was required but did not happen, the receipt must record `TOOL_BLOCKED` or `thread_not_converged`.
- Automation lifecycle is a release gate: due heartbeats must dispatch, dispatch pending, report `TOOL_BLOCKED`, or record `thread_not_converged`; in-flight failure-mode fixes must name a bounded self-improvement/SKM patch path; completed automations must delete or pause themselves and record self-recycle evidence.
- A heartbeat run with `target_thread_verified: false`, `unknown`, or "未验证" is not valid progress evidence. It must be recorded as unknown/misconfigured or blocked, not counted as a successful heartbeat run.
- Release readiness, public repository publishing, reusable Skill hardening, and multi-file reliability validation are routed triggers even when the prompt does not say "Chief of Staff".
- For stronger default routing, add [references/AGENTS_ROUTING_SNIPPET.md](references/AGENTS_ROUTING_SNIPPET.md) to `AGENTS.md` manually or with `scripts/install_skill.py --agents-routing project`, because `AGENTS.md` is read before task work while Skills are selected on demand.

Regression prompts live in [evals/activation.prompts.csv](evals/activation.prompts.csv).
Black-box complex-task prompts live in [evals/blackbox_complex.prompts.csv](evals/blackbox_complex.prompts.csv). They intentionally avoid `$skill`, Chief-of-Staff, thread, receipt, and cleanup wording so the gate can track whether implicit complex-task routing and implicit dispatch-or-TOOL_BLOCKED decisions still have realistic coverage.
Output-level contract fixtures live in [evals/activation_contract.fixture.json](evals/activation_contract.fixture.json), covering the historical failure cases where a pending worktree or same-thread simulation is incorrectly treated as a real dispatch.

## Quality Gate

Run the full package quality gate:

```bash
bash scripts/quality_gate.sh .
```

The same gate is wired into GitHub Actions at `.github/workflows/ci.yml` for public pull requests and pushes across Python 3.10, 3.11, and 3.12.

ThreadOps validation is documented in [validation/THREADOPS_VALIDATION.md](validation/THREADOPS_VALIDATION.md). The local pilot harness intentionally skips live Codex Thread creation; release claims must also cite a fresh Agency-flow receipt in [validation/AGENCY_FLOW_PILOT.md](validation/AGENCY_FLOW_PILOT.md). Council or release-review receipts cannot substitute for SKS/AGS/DEV/REV worker receipts.

Release convergence is centralized in [validation/release_receipt.json](validation/release_receipt.json) and summarized in [validation/RELEASE_RECEIPT.md](validation/RELEASE_RECEIPT.md). It enforces `max_review_waves`, `max_parallel_reviewers_per_deliverable`, required `add_review_wave_reason`, stuck-review rescue, and the stop condition after one cold review plus one domain/rebuttal review converge.

Domain deliverable readiness is validated separately:

```bash
python3 scripts/validate_domain_deliverable_contract.py .
```

This blocks the common false-positive where a worker receipt, green script, or `VALIDATION=PASS` is treated as proof that a creative, storyboard, proposal, research, copy, story, execution-plan, or planning deliverable is client-ready. Client-ready claims require `DOMAIN_DELIVERABLE_RECEIPT` with brief trace, artifacts, passing domain quality gates, validation evidence, `review_status: cold_reviewed_and_domain_reviewed`, and `verdict: PASS`.

Run a lighter release smoke check:

```bash
bash scripts/release_smoke.sh .
```

Generate deterministic local pilot artifacts:

```bash
python3 scripts/pilot_harness.py --root . --out /tmp/agency-thread-pilot
```

Audit local historical runs that used this Skill:

```bash
python3 scripts/audit_historical_threads.py --repo-root . --scan-rollouts --output /tmp/HISTORICAL_THREAD_AUDIT_RECEIPT.json
```

The history audit is intentionally local-only. It scans Codex thread metadata and rollout logs for activation, dispatch, pending worktree, missing cwd/worktree, title/readback, non-converged review, and cross-project routing risks without copying raw conversation text into the receipt.

## What Good Looks Like

This skill is release-ready only when:

- `bash scripts/quality_gate.sh .` passes.
- The installed skill copy matches the source bundle.
- Scripts have useful `--help`, bounded output, and JSON modes where useful.
- Real Codex Thread work records thread ids, receipts, and cleanup.
- Historical-thread audits classify old failures without treating `pendingWorktreeId`, title self-report, missing-cwd workers, or `thread_not_converged` as success evidence.
- A full Agency-flow pilot has converged SKS, AGS, DEV, and REV receipts in `validation/AGENCY_FLOW_PILOT.md`.
- A valid release convergence receipt unifies dispatch, adoption/rejection, cleanup, and review verdicts in `validation/release_receipt.json`.
- Domain deliverables use `DOMAIN_DELIVERABLE_RECEIPT`; thread/process PASS is not treated as creative or client-ready quality PASS.
- If real Codex Thread tooling is unavailable, the correct result is `TOOL_BLOCKED`, not simulated worker evidence.
- Stuck workers are marked `thread_not_converged` and rescued instead of silently treated as success.
- Light tasks stay T0/T1 and do not generate management ceremony.

## Repository Layout

```text
SKILL.md                 Core skill instructions and trigger metadata
agents/openai.yaml       Codex UI metadata
assets/                  Templates and role prompts
references/              Progressive-disclosure operating rules
scripts/                 Install, discovery, scoring, validation, pilot, quality gate
examples/                Realistic forward-test prompts
evals/                   Activation and dispatch regression prompts
```

## Status

Current status: open-source-ready package with local release checks.

The skill has an install script, deterministic pilot artifacts, real ThreadOps receipt notes, explicit thread rescue rules, and a release quality gate. Each public release should be paired with a committed tag, passing CI, and fresh-clone validation.

Note: the slug `zhijuan-codex-agency-chief-of-staf` preserves the originally requested package name for compatibility.
