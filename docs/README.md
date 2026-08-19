# Agency Chief of Staff for Codex — Documentation

> Status: Current documentation index
>
> As of: 2026-08-19
>
> Reviewed release target: `v0.3.0-rc.5`; publication requires tag, Release, and API readback
>
> Evidence boundary: this index describes the repository; it does not prove model behavior, cross-host compatibility, or stable-release eligibility.

`agency-chief-of-staff` is a content-first Codex Desktop / Codex CLI Skill. It keeps one-off and single-session work on a light Root-owned path, and adds durable planning, a separate execution session, progress, verification, archive, and reusable knowledge only for explicit project-lifecycle intent.

`agency-chief-of-staff` 是面向 Codex Desktop / Codex CLI 的内容优先、结果负责型 Skill：单次和单会话任务默认由 Root 直接完成；只有明确的项目生命周期意图才增加持久化清单、独立执行对话、按需团队、进度、归档与长期知识。

## Start here

- [Project overview and installation](../README.md)
- [LLM-friendly documentation index](../llms.txt)
- [Repository discovery and release metadata](REPOSITORY_DISCOVERY.md)
- [Canonical Skill instructions](../SKILL.md)
- [Content-first runtime design](CONTENT_FIRST_DESIGN.md)
- [Real-world prompts](../examples/real-world-prompts.md)
- [Changelog](../CHANGELOG.md)
- [Contributing](../CONTRIBUTING.md)
- [Security policy](../SECURITY.md)
- [Code of Conduct](../CODE_OF_CONDUCT.md)

## Runtime guidance

These files are loaded on demand by the Skill. They describe operating contracts, not evidence that a particular run succeeded.

- [User experience and visualization](../references/user-experience.md)
- [Software development routing](../references/software-development.md)
- [Delivery and independent review](../references/delivery-review.md)
- [Real Codex tasks and threads](../references/real-threads.md)
- [Long-running work](../references/long-running-work.md)
- [Historical task and thread audit](../references/history-audit.md)
- [Model routing and budget](../references/model-routing-and-budget.md)
- [Project task lifecycle](../references/task-lifecycle.md)
- [Deterministic team orchestration](../references/team-orchestration.md)
- [Execution session launch and recovery](../references/execution-session.md)
- [Archive and knowledge deposition](../references/knowledge-archiving.md)

The four-stage lifecycle is intent-gated. Plan creation uses one deterministic call for a complete nonexecuting task bundle; live Team selection, model resolution, Session binding, evidence, and archive work remain lazy. Team planning first applies a net-execution-value gate; it does not restore a fixed organization, require every task to create a Thread, or force routine review. Only Team Plan selected Profiles are prepared, and Execution Root model requests remain separate from Subagent routing.

The rc.4 fast path treats durable state as a continuity and evidence layer, not the work itself. rc.5 retains that boundary while adding deterministic Execution Root title requests, explicit mode/scenario guidance, and regression gates for Native-required fallback plus planner/profile policy parity. Stable helper exit-0 JSON normally ends a lifecycle step; failed calls count against model-smoke overhead budgets, and prior canonical progress is read once only when a resumed task actually has evidence to recover.

Large local Skill catalogs can exhaust Codex's metadata context budget, remove every Skill description, and omit later-sorted names before inference. The installed two-file `agency-discuss-plan-execute-progress-archive` discovery bridge stays near the Canonical entry and improves discovery while its name or description remains visible, but it cannot guarantee natural-language activation after the host removes every description. The deterministic fallback is explicit `$agency-chief-of-staff`; Execution Session packets include that reference automatically. The bridge does not duplicate orchestration or add work to Direct Mode.

## Design and historical records

These records explain prior decisions or implementation work. Their embedded version, interface, and release statements are snapshots, not current compatibility claims.

- [Content-first runtime design](CONTENT_FIRST_DESIGN.md) — current source-candidate problem statement, comparison research, overhead budgets, and evidence boundary; intentionally excluded from Runtime.
- [vNext design decision](VNEXT_DESIGN.md) — accepted design record; implementation state is superseded by the current source tree.
- [Codex Desktop hardening handoff](CODEX_DESKTOP_HARDENING_HANDOFF_2026-07-15.md) — superseded implementation brief; its findings must not be treated as current open defects without reproduction.
- [Master handoff](MASTER_HANDOFF.md) — historical task handoff and authorization boundary.

## How to read verification claims

- Repository tests and `quality_gate.sh` establish only the checks they execute.
- A release note is maintainer-reported evidence unless it links to a reproducible artifact or public run.
- Model, native task/thread, reviewer, and cross-host claims require their own current evidence.
- Current release status comes from the repository's Releases page and current validation, not from a historical document in this directory.
