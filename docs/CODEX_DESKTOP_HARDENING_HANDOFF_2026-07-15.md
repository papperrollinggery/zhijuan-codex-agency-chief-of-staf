# Codex Desktop hardening handoff

> Status: Superseded implementation brief
>
> As of: 2026-07-15
>
> Superseded by: the `v0.2.0-rc.2` source tree and its [changelog entry](../CHANGELOG.md#v020-rc2---2026-07-15)
>
> Evidence boundary: the findings below were review inputs, not current defect status. The current source and fresh tests must reproduce or reject them. This file does not prove model behavior, native task/thread behavior, or release readiness.

The rc.2 changelog records follow-up work across the worker/reviewer contracts, artifact-read provenance, visualization data gates, routing, and native receipt boundaries. Do not cite the P0/P1 labels below as unresolved current defects without checking the current implementation.

## Product boundary

This repository is intentionally a Codex Desktop / Codex CLI host-scoped Skill. Cross-host portability is not a product goal for this workstream. Do not split the project into a generic cross-host core and adapters, and do not downgrade the design merely because it depends on Codex-native Goal, task/thread, state, rollout, visualization, or archive capabilities.

The useful external review is the defect evidence inside that boundary. Treat every finding below as a hypothesis to reproduce against the current checkout before changing code.

External review source: private maintainer-provided review; intentionally omitted from the public package.

## Objective

Make the Skill internally consistent, evidence-honest, and ready for real Codex Desktop use. Preserve its current strengths: main-thread outcome ownership, minimal role selection, current-artifact verification, bounded independent review, human-facing interaction, and no implicit `AGENTS.md` modification.

## Required workflow

The receiving main thread owns the outcome. It must:

1. Inspect the current repository and reproduce or reject each finding below with file-and-test evidence.
2. Produce a short implementation plan ordered by risk and dependency.
3. Use real Codex tasks/threads for independent read-only research and cold review when useful. Use isolated worktrees or non-overlapping write scopes for execution threads.
4. Read back real thread IDs and statuses. A planned or pending thread is not execution evidence.
5. Integrate only verified changes, run the relevant gates, and keep a dispatch ledger.
6. Do not publish, push, merge, or create a release without fresh user authorization.
7. Do not modify or inject `AGENTS.md` as a routing shortcut.

## Historical findings from the handoff

The severity labels in this section describe the review priority at the time of the handoff. They are retained for traceability and are not a current issue tracker.

### Historical P0 — one worker packet contract

The main Skill requires a fixed worker packet and an exact stop condition, while `references/real-threads.md` appears to add `真实 task/thread id` as another packet field. Verify whether the documented real-thread packet is rejected by the canonical parser/runner or can cause a child to be treated as a new main session.

Done when one canonical machine-readable contract drives or is checked against:

- `SKILL.md`
- `references/real-threads.md`
- runner/parser code
- agent profiles
- behavior cases and tests

Thread identity belongs in the dispatch receipt or host metadata unless the canonical schema explicitly includes it. Markdown examples must be exercised by tests, not only visually reviewed.

### Historical P0 — one reviewer terminal contract

Production profile and native receipt paths use a five-field reviewer terminal, while model smoke currently appears to use a three-field terminal. Reproduce the incompatibility, then establish one canonical reviewer schema across profiles, runner, native verifier, model evals, fixtures, references, and examples.

Done when an output accepted by model smoke is accepted by the production reviewer parser and native receipt verifier, and malformed, duplicate, reordered, or extra-field outputs fail closed.

### Historical P1 — strengthen artifact-read provenance

Verify whether a command that mentions the target artifact but obtains the marker from another file can satisfy `command_reads_artifact()` / `verify_direct_read()`.

If reproduced, bind proof to one successful tool call, one target artifact, and the bytes or hash actually observed. Do not claim full provenance from argument-string presence alone. Add adversarial regression tests.

### Historical P1 — make native receipt claims match proof

Audit claims such as “zero out-of-scope writes”, `agents_md.unchanged`, and minimal read scope against what the verifier actually measures. Prefer strengthening the receipt with start/end HEAD, before/after status, allowed and actual changed paths, diff/artifact hashes, validation exit codes, and reviewer read timing. Where stronger proof is unavailable, narrow user-facing wording instead of overstating it.

### Historical P1 — complete useful visualization paths without decorative noise

Keep visualization selective and user-facing. Do not add fake curves, placeholder image previews, decorative dashboards, internal receipts, hashes, JSON, callback values, or code-like runtime details to the normal chat surface.

Verify and improve only the surfaces justified by real state or data:

- compact task stage for multi-step work;
- decision surface for genuine user choices;
- evidence list for concise verification results;
- numeric trend only when comparable numeric observations exist;
- image review only when a real image or page is available.

The visual layer must remain compact, responsive, stable on hover, accessible in light/dark themes, and free of animation/flicker. Add schema/data binding and mount/readback validation where the host supports it. A keyword appearing in Markdown is not proof that a visualization rendered.

### Historical P2 — routing and documentation precision

Keep role/model selection as a cost-aware plan unless the host confirms the accepted model override and actual execution identity. Separate concurrency from total delegation count. Validate the full supplied catalog or label exactly what subset was validated.

Reconcile documentation with current runtime facts, including runtime allowlist size, model-slug wording, release-evidence wording, domain Skill rules, and the distinction between maintainer-reported verification and publicly reproducible evidence.

## Explicit non-goals

- Cross-host or Claude/Faber implementation.
- A universal multi-agent framework.
- Restoring a large fixed company org chart.
- Adding every chart or visualization type.
- Cosmetic visual complexity without real user information.
- Replacing Codex-native orchestration with a custom scheduler.

Leave a documented extension point for a future optional Faber/Claude adapter, but do not implement or test it in this workstream.

## Verification and release gate

At minimum, run the current package, behavior, profile, routing, receipt, model-eval unit, and quality gates relevant to touched files, plus `git diff --check`. Add targeted regression tests for every reproduced protocol or provenance defect.

Before declaring delivery-ready, require an independent cold review that reads the final diff and current artifacts. Report only one of:

- `已验证`
- `未验证`
- `验证失败`

Do not equate offline tests with native Codex task/thread proof. Do not equate a previous receipt with current-HEAD evidence.

## Deliverables

- Reproduction matrix: accepted, rejected, or not reproducible for every finding.
- Minimal implementation changes and regression tests.
- Updated user-facing documentation with Codex Desktop scope stated positively.
- Dispatch ledger with real thread IDs, scopes, adoption, and cleanup status.
- Final validation receipt tied to the current diff/HEAD.
- Release recommendation; no release action without user authorization.
