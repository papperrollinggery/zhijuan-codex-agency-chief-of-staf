# ThreadOps Validation

Date: 2026-07-03

This file records live Codex Thread validation for the Skill release line. Some older receipts were collected during release-candidate phases and are retained as historical evidence. The deterministic local harness deliberately marks case 08 as `skipped_by_local_harness` because a shell script cannot create real Codex Threads. A release claim must therefore cite real thread receipts, not only the local harness.

Current verified release baseline:

- release: `v0.1.4`
- commit: `f059a5330d50be9e24fcaf93e17777e730241bbb`
- CI: GitHub Actions quality run `28608717443` completed with success.
- fresh_clone_validation: completed after push; `bash scripts/quality_gate.sh .`, temporary install, and installed-copy `release_smoke.sh` all exited 0.

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

### COS Title Smoke Receipt

- thread_id: `019f23cc-d948-7253-8daa-d9da89ef2e79`
- receipt: `TITLE_SMOKE_RECEIPT`
- purpose: verify whether a newly created COS smoke thread reliably applies the required Chief-of-Staff title.
- expected_title: `[P01-TH00-R00] 幕僚长-COS｜主控沟通｜TASK-000｜OUT-000`
- observed_sequence:
  - initial `read_thread`: title `null`; turn in progress.
  - later `read_thread`: title `验证线程自标题`, not the required COS title.
  - convergence reminder was queued while the first turn was still in progress.
  - coordinator fallback called `set_thread_title` with the expected title.
  - final `read_thread`: title matched the expected title and status was idle.
- worker_receipt: worker later reported `title_action: set_thread_title`, but the receipt is not adopted as independent self-title proof because coordinator fallback happened before the final receipt.
- adopted_result: `dispatcher_set`
- verdict: the title discipline must be two-layered: self-title when the tool is available inside the thread, plus coordinator title fallback and metadata verification for every created/reused Codex Thread.

### Post-Title Delta Council

- thread_id: `019f23d3-189f-76c2-bc90-e8d6f9e2f38b`
- voice: Skeptic
- receipt: `POST_TITLE_DELTA_COUNCIL_RECEIPT`
- verdict: FAIL
- adopted_blocker: `assets/REVIEWER_PROMPT.md` lacked the same COS isolation guard added to `assets/EXECUTOR_PROMPT.md`.
- adoption: accepted; Reviewer prompt and quality gate were updated.

- thread_id: `019f23d3-2b5f-7c93-8339-57debef85e66`
- voice: Pragmatist
- receipt: `POST_TITLE_DELTA_COUNCIL_RECEIPT`
- verdict: PASS
- evidence: quality gate exit_code=0; install dry-run exit_code=0; title-smoke evidence does not overclaim self-title proof.
- adoption: accepted after applying the Skeptic blocker.

- thread_id: `019f23d3-3532-70d3-886b-6457d15d801c`
- voice: Critic
- receipt: none
- verdict: rejected evidence
- reason: the thread was interrupted by cleanup before producing a receipt, so it is not counted as council PASS evidence.

- thread_id: `019f23d5-6c4e-7052-b484-b97eff20403e`
- voice: Final Critic
- receipt: `FINAL_CRITIC_RELEASE_RECEIPT`
- verdict: PASS
- evidence: quality gate exit_code=0; install dry-run exit_code=0; title-smoke evidence does not launder dispatcher fallback; executor and reviewer prompts both contain COS isolation guards.
- adoption: accepted as the post-fix final release critic receipt.

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
- verdict: pre-release ready-to-ship finding
- limitation adopted: real external user use remained unvalidated at receipt time.
- superseded_by: `v0.1.4` fresh-clone validation.

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
- verdict: pre-release ready-to-ship finding
- blocking_findings: none

- thread_id: `019f2391-29e5-7bb3-b494-c508391f6c7a`
- voice: Pragmatist
- receipt: `POST_FIX_COUNCIL_RECEIPT`
- commands:
  - `git status --short` exit_code=0
  - `bash scripts/quality_gate.sh .` exit_code=0
  - `python3 scripts/install_skill.py --dry-run --json` exit_code=0
  - `diff -qr -x .git -x .codex /Users/jinjungao/.agents/skills/zhijuan-codex-agency-chief-of-staf .` exit_code=0
- verdict: pre-release ready-to-ship finding
- blocking_findings: none

- thread_id: `019f2391-2bc4-7021-887b-d4993ffeb5f4`
- voice: Critic
- receipt: `POST_FIX_COUNCIL_RECEIPT`
- commands:
  - `git status --short` exit_code=0
  - `bash scripts/quality_gate.sh .` exit_code=0
  - `python3 scripts/install_skill.py --dry-run --json` exit_code=0
  - `diff -qr -x .git -x .codex /Users/jinjungao/.agents/skills/zhijuan-codex-agency-chief-of-staf .` exit_code=0
- verdict: pre-release ready-to-ship finding
- blocking_findings: release required commit/tag and fresh-clone validation at receipt time.
- superseded_by: `v0.1.4` release validation.

- thread_id: `019f2391-2dd1-76c3-b11f-904660fe0350`
- class: post-fix realistic forward test
- receipt: `POST_FIX_FORWARD_TEST_RECEIPT`
- commands:
  - `bash scripts/quality_gate.sh .` exit_code=0
  - `python3 scripts/install_skill.py --dry-run --json` exit_code=0
  - `diff -qr -x .git -x .codex /Users/jinjungao/.agents/skills/zhijuan-codex-agency-chief-of-staf .` exit_code=0
  - `git status --short` exit_code=0
- verdict: pre-release ready-to-ship finding
- blocking_findings: none

## Adopted Fixes

- `SKILL.md` now names section 2.6 as `Codex Threads / Workers`.
- The Skill states that Codex Threads are not subagents and that TOOL_BLOCKED is required when real thread tools are unavailable.
- `references/CODEX_CONTROL_SURFACE.md` and `references/DELEGATION_CHAIN.md` now distinguish real Codex Threads from lightweight subagents.
- COS and worker thread title rules now require coordinator `set_thread_title` fallback plus `read_thread` / `list_threads` metadata verification; worker self-report alone is insufficient.
- `assets/REVIEWER_PROMPT.md` now has the same "do not load or impersonate full COS Skill" role-isolation guard as the executor prompt.
- `scripts/quality_gate.sh` requires this file and checks for explicit council and forward-test receipt evidence.

## Cleanup

- `019f236d-f646-7161-b16d-1d44e06a5cc2`: archived after final receipt adoption.
- `019f2391-2838-79a1-8675-8381bcc6a249`: archived after post-fix receipt adoption.
- `019f2391-29e5-7bb3-b494-c508391f6c7a`: archived after post-fix receipt adoption.
- `019f2391-2bc4-7021-887b-d4993ffeb5f4`: archived after post-fix receipt adoption.
- `019f2391-2dd1-76c3-b11f-904660fe0350`: archived after post-fix receipt adoption.
- `019f23cc-d948-7253-8daa-d9da89ef2e79`: archived after title smoke adoption.
- `019f23d3-189f-76c2-bc90-e8d6f9e2f38b`: archived after Skeptic blocker adoption.
- `019f23d3-2b5f-7c93-8339-57debef85e66`: archived after Pragmatist receipt adoption.
- `019f23d3-3532-70d3-886b-6457d15d801c`: archived as interrupted / rejected evidence.
- `019f23d5-6c4e-7052-b484-b97eff20403e`: archived after final Critic PASS receipt adoption.

## Limits

- The current evidence supports `v0.1.4` local and fresh-clone release validation, not guaranteed public adoption.
- No claim of "1000 star" quality is evidence-backed until external users, issues, stars, or independent adoption prove it.
- Future releases must not be called complete until the working tree is committed/tagged and fresh-clone validation is run.
