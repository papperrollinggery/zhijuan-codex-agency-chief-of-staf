# Agency Chief of Staff for Codex — Documentation

> Status: Current documentation index
>
> As of: 2026-07-19
>
> Reviewed source candidate: `v0.3.0-rc.1`; unpublished and not an installed-state claim
>
> Evidence boundary: this index describes the repository; it does not prove model behavior, cross-host compatibility, or stable-release eligibility.

`agency-chief-of-staff` is a Codex Desktop / Codex CLI host-scoped Skill with a project lifecycle from requirements discussion through durable planning, a separate execution session, progress, verification, archive, and reusable knowledge. One-off work still uses Direct Mode.

`agency-chief-of-staff` 是面向 Codex Desktop / Codex CLI 的结果负责型 Skill：项目型请求可从需求讨论推进到持久化清单、独立执行对话、团队执行、验证、归档与长期知识；单次任务继续使用 Direct Mode。

## Start here

- [Project overview and installation](../README.md)
- [LLM-friendly documentation index](../llms.txt)
- [Repository discovery and release metadata](REPOSITORY_DISCOVERY.md)
- [Canonical Skill instructions](../SKILL.md)
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

The four-stage lifecycle is intent-gated. It does not restore a fixed organization, does not require every task to create a Thread, prepares only Team Plan selected Profiles, and keeps the Execution Root model request separate from Subagent routing.

## Design and historical records

These records explain prior decisions or implementation work. Their embedded version, interface, and release statements are snapshots, not current compatibility claims.

- [vNext design decision](VNEXT_DESIGN.md) — accepted design record; implementation state is superseded by the current source tree.
- [Codex Desktop hardening handoff](CODEX_DESKTOP_HARDENING_HANDOFF_2026-07-15.md) — superseded implementation brief; its findings must not be treated as current open defects without reproduction.
- [Master handoff](MASTER_HANDOFF.md) — historical task handoff and authorization boundary.

## How to read verification claims

- Repository tests and `quality_gate.sh` establish only the checks they execute.
- A release note is maintainer-reported evidence unless it links to a reproducible artifact or public run.
- Model, native task/thread, reviewer, and cross-host claims require their own current evidence.
- Current release status comes from the repository's Releases page and current validation, not from a historical document in this directory.
