# ThreadOps Validation

Date: 2026-07-03

This file records live Codex Thread validation for the Skill release candidate. The deterministic local harness deliberately marks case 08 as `skipped_by_local_harness` because a shell script cannot create real Codex Threads. A release claim must therefore cite real thread receipts, not only the local harness.

## Receipts Reviewed

### User Test Thread

- thread_id: `019f236d-f646-7161-b16d-1d44e06a5cc2`
- class: user-created release-prep test thread
- status: final receipt reviewed; thread archived after adoption
- receipt: `TEST_THREAD_OPEN_SOURCE_FINAL_RECEIPT`
- commands:
  - `bash scripts/quality_gate.sh .` exit_code=0
  - `python3 scripts/install_skill.py --dry-run --json` exit_code=0
  - `diff -qr -x .git -x .codex /Users/jinjungao/.agents/skills/zhijuan-codex-agency-chief-of-staf .` exit_code=0
  - `test -f .github/workflows/ci.yml && test -f README.md && test -f examples/real-world-prompts.md` exit_code=0
- adoption: final read-only verification adopted; no remaining worker worktree changes to merge

### Council Receipts

- thread_id: `019f2391-2838-79a1-8675-8381bcc6a249`
- voice: Skeptic
- receipt: `COUNCIL_RECEIPT`
- verdict: practical-ready
- strongest objection adopted: local pilot case 08 is skipped and must not be counted as real ThreadOps validation by itself

- thread_id: `019f2391-29e5-7bb3-b494-c508391f6c7a`
- voice: Pragmatist
- receipt: `COUNCIL_RECEIPT`
- verdict: pilot-ready before protocol fix
- strongest objection adopted: `Subagents` wording was not strict enough for real Codex Thread discipline

- thread_id: `019f2391-2bc4-7021-887b-d4993ffeb5f4`
- voice: Critic
- receipt: `COUNCIL_RECEIPT`
- verdict: practical-ready
- strongest objection adopted: open-source trust material must be committed before a public release claim

### Forward Test Receipt

- thread_id: `019f2391-2dd1-76c3-b11f-904660fe0350`
- class: realistic user-task forward test
- receipt: `FORWARD_TEST_RECEIPT`
- commands:
  - `bash scripts/quality_gate.sh .` exit_code=0
  - `python3 scripts/install_skill.py --dry-run --json` exit_code=0
  - `diff -qr -x .git -x .codex /Users/jinjungao/.agents/skills/zhijuan-codex-agency-chief-of-staf .` exit_code=0
  - `python3 scripts/pilot_harness.py --root . --out <tmp> --json` exit_code=0
  - `git status --short` exit_code=0
- verdict: open-source-ready candidate
- limitation adopted: fresh-clone install and real external user use remain unvalidated

## Post-Fix Re-Review

After adopting the first council findings, the same live Codex Threads rechecked the main working tree at `/Users/jinjungao/work/zhijuan-codex-agency-chief-of-staf`.

- thread_id: `019f2391-2838-79a1-8675-8381bcc6a249`
- voice: Skeptic
- receipt: `POST_FIX_COUNCIL_RECEIPT`
- commands:
  - `git status --short` exit_code=0
  - `bash scripts/quality_gate.sh .` exit_code=0
  - `python3 scripts/install_skill.py --dry-run --json` exit_code=0
  - `diff -qr -x .git -x .codex /Users/jinjungao/.agents/skills/zhijuan-codex-agency-chief-of-staf .` exit_code=0
- verdict: open-source-ready candidate
- blocking_findings: none

- thread_id: `019f2391-29e5-7bb3-b494-c508391f6c7a`
- voice: Pragmatist
- receipt: `POST_FIX_COUNCIL_RECEIPT`
- commands:
  - `git status --short` exit_code=0
  - `bash scripts/quality_gate.sh .` exit_code=0
  - `python3 scripts/install_skill.py --dry-run --json` exit_code=0
  - `diff -qr -x .git -x .codex /Users/jinjungao/.agents/skills/zhijuan-codex-agency-chief-of-staf .` exit_code=0
- verdict: open-source-ready candidate
- blocking_findings: none

- thread_id: `019f2391-2bc4-7021-887b-d4993ffeb5f4`
- voice: Critic
- receipt: `POST_FIX_COUNCIL_RECEIPT`
- commands:
  - `git status --short` exit_code=0
  - `bash scripts/quality_gate.sh .` exit_code=0
  - `python3 scripts/install_skill.py --dry-run --json` exit_code=0
  - `diff -qr -x .git -x .codex /Users/jinjungao/.agents/skills/zhijuan-codex-agency-chief-of-staf .` exit_code=0
- verdict: open-source-ready candidate
- blocking_findings: public release still requires commit/tag and fresh-clone validation

- thread_id: `019f2391-2dd1-76c3-b11f-904660fe0350`
- class: post-fix realistic forward test
- receipt: `POST_FIX_FORWARD_TEST_RECEIPT`
- commands:
  - `bash scripts/quality_gate.sh .` exit_code=0
  - `python3 scripts/install_skill.py --dry-run --json` exit_code=0
  - `diff -qr -x .git -x .codex /Users/jinjungao/.agents/skills/zhijuan-codex-agency-chief-of-staf .` exit_code=0
  - `git status --short` exit_code=0
- verdict: open-source-ready candidate
- blocking_findings: none

## Adopted Fixes

- `SKILL.md` now names section 2.6 as `Codex Threads / Workers`.
- The Skill states that Codex Threads are not subagents and that TOOL_BLOCKED is required when real thread tools are unavailable.
- `references/CODEX_CONTROL_SURFACE.md` and `references/DELEGATION_CHAIN.md` now distinguish real Codex Threads from lightweight subagents.
- `scripts/quality_gate.sh` requires this file and checks for explicit council and forward-test receipt evidence.

## Cleanup

- `019f236d-f646-7161-b16d-1d44e06a5cc2`: archived after final receipt adoption.
- `019f2391-2838-79a1-8675-8381bcc6a249`: archived after post-fix receipt adoption.
- `019f2391-29e5-7bb3-b494-c508391f6c7a`: archived after post-fix receipt adoption.
- `019f2391-2bc4-7021-887b-d4993ffeb5f4`: archived after post-fix receipt adoption.
- `019f2391-2dd1-76c3-b11f-904660fe0350`: archived after post-fix receipt adoption.

## Limits

- The current evidence supports a local open-source-ready candidate, not guaranteed public adoption.
- No claim of "1000 star" quality is evidence-backed until external users, issues, stars, or independent adoption prove it.
- The project is not a public release until the working tree is committed/tagged and fresh-clone validation is run.
