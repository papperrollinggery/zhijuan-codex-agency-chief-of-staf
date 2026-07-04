# Zhijuan Codex Agency Chief of Staff

Dynamic Chief-of-Staff Agency workflow for Codex.

This skill helps Codex decide whether a request should be handled directly, planned first, tracked as a long-running goal, delegated to real Codex Threads, reviewed independently, rescued, or turned into a reusable improvement. It is designed for users who want a high-autonomy Codex workflow without losing evidence, receipts, or cleanup discipline.

## Why Use It

- Classifies tasks from T0 to T5 instead of forcing every request into the same process.
- Keeps light tasks light: no unnecessary Task Graphs, teams, or packets.
- Uses Plan and Goal mode only when the task benefits from them.
- Routes work to Skills, Agents, or Codex Threads with explicit scope and receipts.
- Treats Codex Threads as a real execution surface, not a synonym for subagents.
- Emits `COS_BOOT_RECEIPT` first when explicitly invoked, so a run cannot silently skip the Chief-of-Staff startup.
- Treats stuck threads as recoverable failures through bounded rescue.
- Enforces release review convergence budgets and a single release receipt table.
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
- Release readiness, public repository publishing, reusable Skill hardening, and multi-file reliability validation are routed triggers even when the prompt does not say "Chief of Staff".
- For stronger default routing, add [references/AGENTS_ROUTING_SNIPPET.md](references/AGENTS_ROUTING_SNIPPET.md) to `AGENTS.md`, because `AGENTS.md` is read before task work while Skills are selected on demand.

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

The history audit is intentionally local-only. It scans Codex thread metadata and rollout logs for activation, dispatch, pending worktree, title/readback, non-converged review, and cross-project routing risks without copying raw conversation text into the receipt.

## What Good Looks Like

This skill is release-ready only when:

- `bash scripts/quality_gate.sh .` passes.
- The installed skill copy matches the source bundle.
- Scripts have useful `--help`, bounded output, and JSON modes where useful.
- Real Codex Thread work records thread ids, receipts, and cleanup.
- Historical-thread audits classify old failures without treating `pendingWorktreeId`, title self-report, or `thread_not_converged` as success evidence.
- A full Agency-flow pilot has converged SKS, AGS, DEV, and REV receipts in `validation/AGENCY_FLOW_PILOT.md`.
- A valid release convergence receipt unifies dispatch, adoption/rejection, cleanup, and review verdicts in `validation/release_receipt.json`.
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
