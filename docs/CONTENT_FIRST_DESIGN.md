# Content-first runtime design

> Status: `v0.3.0-rc.4` source-candidate design record
>
> Runtime boundary: this file is maintainer evidence and is not installed in either Skill bundle.

## Problem statement

The previous runtime alternated between two bad defaults: a fixed organization with heavy receipts, and a light Root path that had no durable project lifecycle. Both made complexity a poor proxy for the controls a task actually needed.

The 2026-07-19 pre-change audit found a 261-line main Skill, a roughly 374-line mandatory reading path, and about 72 KB of guidance on a normal execution path. Creating a plan eagerly materialized nine task files; a work-item start or completion could rewrite four views of the same state. The Team Planner could also delegate a single research, writing, or implementation stream even when no parallel or isolation benefit existed. These costs competed directly with project reading, judgment, implementation, and verification.

The product requirement is therefore not “more orchestration” or “less orchestration.” It is:

> Every control action must unlock project judgment, coordinate real parallelism, or prove the current result. Otherwise skip it.

## External patterns used

- OpenAI's [Harness engineering](https://openai.com/index/harness-engineering/) keeps the root instructions as a short map, moves detail into discoverable references, and distinguishes lightweight plans from durable execution plans. We adopted the map and progressive-disclosure pattern, not its repository-specific structure.
- OpenAI's [Codex subagents guidance](https://learn.chatgpt.com/docs/agent-configuration/subagents) keeps requirements, decisions, integration, and final judgment with the main agent while delegating independent, context-heavy work. We adopted that ownership boundary.
- OpenAI's [Skills guidance](https://learn.chatgpt.com/docs/build-skills) treats Skill instructions as a routing layer over scripts and references. We kept deterministic state, routing, and validation in scripts instead of expanding the prompt.
- Anthropic's [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) recommends the simplest composable pattern that reliably improves results. Anthropic's [multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system) also makes the token and coordination cost of multi-agent execution explicit. We therefore require net execution value before delegation.
- Anthropic's [long-running agent harness](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) uses persistent state to bridge context windows. We use durable files only when work really crosses conversations, rather than as a default task wrapper.
- Anthropic's [agent evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) measures outcomes and execution traces, not a ceremonial phrase. The evaluation suite now checks artifacts, state, collaboration attempts, management-file budgets, progress, archive, and knowledge patches.

## Runtime decision ladder

| Mode | Use it when | Default overhead budget |
| --- | --- | --- |
| Direct | One target can close safely in the current conversation | No `.agency`; no team; no Thread; no model query; no receipt |
| Focused | Related multi-step work needs a short in-thread plan | No persistent management files; delegate only for demonstrated net value |
| Durable | The user explicitly needs cross-conversation continuity, a checklist, progress, or a separate execution task | One deterministic helper writes the complete nonexecuting plan bundle; live team/model/session/evidence work stays lazy |
| Assured | Release, security, high-risk migration, audit, or an explicit evidence request needs independent proof | Add only the review, identity readback, or receipt required by the risk |

Mode selection is an internal judgment, not a user-facing ceremony. Direct and Focused must reach the first project-content read or analysis after at most one mode decision. Complexity alone never creates persistent state, a team, visualization, model lookup, or review.

## Delegation decision

Root owns the objective, requirements, core judgment, tightly coupled implementation, integration, and final answer. A position is added only when all relevant conditions are true:

1. The work has a self-contained outcome and bounded read/write scope.
2. Isolation or parallelism produces more project value than coordination cost.
3. Concurrent writes do not overlap and use isolated worktrees when necessary.
4. The returned evidence can change or strengthen the Root's result.

A single research stream, document, ordinary file change, or internal architecture decision remains Root-owned. Several genuinely independent research streams may use separate instances of the same profile. Review is risk-triggered; it is not a minimum headcount rule. The recursion depth remains one, with at most three parallel terminal workers.

## Durable-state design

Durable state is normalized at script boundaries so compact plans and full v1.0 plans remain compatible. A real installed-state smoke found that the earlier three-file optimization violated the public plan-bundle contract and made later phases depend on missing files. Plan creation now uses one rollback-safe helper call to write:

```text
.agency/task-index.json
.agency/tasks/active/<task-id>/task-plan.json
.agency/tasks/active/<task-id>/TASK_EXECUTION_CHECKLIST.md
.agency/tasks/active/<task-id>/TEAM_PLAN.json
.agency/tasks/active/<task-id>/TEAM_PLAN.md
.agency/tasks/active/<task-id>/EXECUTION_LAUNCH_PROMPT.md
.agency/tasks/active/<task-id>/PROGRESS.md
.agency/tasks/active/<task-id>/progress.jsonl
.agency/tasks/active/<task-id>/EVIDENCE.md
```

This restores the stable cross-conversation surface without restoring management-heavy reasoning: Team is schema-valid but pending, progress is a zero-event log plus current-state view, evidence explicitly says none exists, and the launch file says no task was created. The helper returns every path, so the model does not enumerate or design these files. It stages and validates the bundle before one directory rename; one reentrant project transaction lock serializes every durable task-state mutation and index rollback, while a tiny recovery journal reconciles an interrupted rename/index window on the next Durable operation. Unknown caller claims fail at the create boundary, while old v1.0 plans remain readable. Live team selection, model resolution, Execution Session, closure, archive, and knowledge work still materialize only when their phase needs them. Team selection and launch snapshot the complete file surface they modify and restore exact prior bytes when any later write, transition, or progress update fails. `complete_task.py` is the single guarded completion path: it requires current acceptance evidence, validation, review when required, and native cleanup/readback before producing a reusable closure, and restores every managed file if any completion write fails. Execution preparation and proof are deliberately separate: `prepare_execution_launch.py` never claims a task exists, while `bind_execution_session.py` internally reads App Server, canonical state, live catalog, and rollout turn context before entering `executing`.

Reserved worker and execution-session markers fail closed. Native `create_thread` may transport an Execution Session inside an exact `<codex_delegation>` envelope; the Runtime unwraps only that host form, rejects Worker/malformed transports, and requires the source to be a user-owned Root in both App Server and canonical state before binding. Legacy v1.0 raw readbacks remain readable and gain transport fields only after a fresh mechanical recheck. Execution Root has orchestration depth zero; its terminal workers cannot invoke this Skill or spawn another layer. Root execution-model resolution remains separate from Subagent cost routing and cannot silently downgrade a requested effort.

## What was deliberately not adopted

- No fixed team, minimum role count, or return to the v0.1 16-role organization.
- No plan, branch, commit, worktree, PR, Thread, visualization, receipt, or knowledge deposit for every task.
- No automatic durable lifecycle merely because a task is complex or explicitly invokes the Skill.
- No removal of permission boundaries, current-result verification, write-conflict isolation, archive gates, or truthful model/Thread readback.
- No global Skill/config update as part of source-candidate validation.

## Release-candidate evidence

The offline gate proves schema, deterministic scripts, installer parity, compatibility, and unit/integration contracts. Model smoke additionally requires a completed installed-Skill read for positive activation and forbids that read for ordinary/worker exclusions; output resemblance alone is not activation evidence. Source-forward model smoke must separately prove behavior in isolated fixtures; Native Task/Thread and actual model/effort claims require current host readback. Passing one evidence layer does not promote another, and only an explicit later decision may update the installed global Skill.

The rc.4 current-host source-forward diagnostic ran the resume, progress, and archive/knowledge cases from exact commit `ef2a2dc` on `gpt-5.6-sol` with `ultra`. All three model/effort identities were read back and the cases passed with 10/13, 7/9, and 7/11 attempted tool events; there were no invalid commands, management-directory enumeration, Git housekeeping, helper-source reads, or `--help` probes. The host-local ignored receipt records `passed_partial` and `release_evidence_eligible=false` because it used the primary credential and no release catalog. It proves only this scoped source-forward behavior, not installation, Native task creation, portability, publication, or stable-release eligibility.

## Testing Native Execution Proof Boundary

A Native execution result is proven only when the execution task is mechanically bound to provider, model, reasoning effort, and isolated CWD, and the requested artifact is independently verified; preparing a launch packet alone is not execution proof.

适用范围：Installed-Skill Native smoke tests and project execution sessions that create or modify files in an isolated Codex worktree.

Source Task: `task-installed-native-20260722-001`
Evidence: execution-session.json readback: openai/gpt-5.6-sol/ultra, isolated_worktree=true；python3 verifier exited 0: regular_file=true, symlink=false, bytes=23, sha256=7b15687d110829cf4e87f19e2aa9f2b5b3963905d571536adc85241eb8796b8d
Knowledge ID: `testing-native-execution-proof-boundary`
