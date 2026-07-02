# Council Rounds Validation

Date: 2026-07-03

Purpose: record three adversarial council rounds before public release. Each round uses real Codex Threads for Skeptic, Pragmatist, and Critic where possible. Non-converging threads are not counted as approval; they are recorded and replaced or carried as risk.

## Round 1: Release Engineering And Repository Reproducibility

Architect initial position: hold public publishing until release files are tracked, a GitHub remote exists, and clone/install validation can be run against the committed tree. Local quality gates are green, but dirty working tree evidence is not enough for public release.

### Receipts

- Skeptic thread: `019f2399-9867-7090-bd1c-8a3ac0baeb9b`
  - receipt: `ROUND1_COUNCIL_RECEIPT`
  - verdict: `hold`
  - strongest objection: quality gate is green, but the repository is dirty, release-critical files are untracked, and no GitHub remote exists.

- Pragmatist thread: `019f2399-9995-7c81-b8c1-160ffa081d89`
  - receipt: `ROUND1_COUNCIL_RECEIPT`
  - verdict: `hold`
  - strongest objection: users clone the committed remote tree, not the local working tree.
  - note: the receipt body reported the source thread id; the actual worker thread id is recorded here from Codex thread metadata.

- Critic thread: `019f2399-9bd2-7792-95c7-ce235534651d`
  - status: `thread_not_converged`
  - action: archived and replaced; not counted as approval.

- Replacement Critic thread: `019f239b-1db6-74c0-b0b8-5547dd6f88ac`
  - receipt: `ROUND1_COUNCIL_RECEIPT`
  - verdict: `hold`
  - strongest objection: no GitHub remote and release-critical files are still uncommitted/untracked.

### Adopted Round 1 Fixes

- Track all public release files in Git.
- Create or connect a public GitHub repository.
- Run quality gate and fresh-clone validation against the committed/pushed tree before claiming release.

## Round 2: Skill Behavior, Thread Discipline, And Real Task Fit

Architect initial position: the Skill is behaviorally strong but still needed proof that realistic helper commands and receipt evidence cannot silently fail. The council found two real gaps: `score_capabilities.py` failed without an explicit inventory file, and the quality gate could pass while later council rounds were still pending.

### Receipts

- Skeptic thread: `019f239c-7850-76b2-9b6d-eb9e92bdd553`
  - receipt: `ROUND2_COUNCIL_RECEIPT`
  - verdict: `fix-minor`
  - strongest objection: real ThreadOps evidence is documented, but not independently replayable by external users.

- Pragmatist thread: `019f239c-7ab1-7e13-90fb-d81b300afd15`
  - receipt: `ROUND2_COUNCIL_RECEIPT`
  - verdict: `hold`
  - strongest objection: `score_capabilities.py --query ... --json` failed in a realistic no-inventory invocation.

- Critic thread: `019f239c-7cff-7811-b87b-0d7c339b0378`
  - receipt: `ROUND2_COUNCIL_RECEIPT`
  - verdict: `hold`
  - strongest objection: quality gate could pass while Round 2/Round 3 were only `Pending`.

### Adopted Round 2 Fixes

- `score_capabilities.py` now auto-scans default local skill and agent roots when no inventory file is provided.
- `release_smoke.sh` now tests a real no-inventory score query, not only `--help`.
- `SKILL.md` now states a runtime untrusted-input boundary.
- `validation/receipts/ROUND2_BEHAVIOR.md` records per-voice evidence.

## Round 3: Public Release Go / No-Go

Architect initial position: conditional go only after the release tree is committed, merged to `main`, published to a public GitHub repository, and validated from a fresh clone. The Skill content and local install sync are strong enough to enter the release flow, but the release claim must remain conditional until remote clone validation passes.

### Receipts

- Skeptic thread: `019f23a0-ba04-7393-883c-f8e88ac67fc3`
  - receipt: `ROUND3_COUNCIL_RECEIPT_CORRECTED`
  - verdict: `go`
  - strongest objection: the initial no-go was a valid process warning caused by checking an isolated worktree index; corrected main-path checks passed, but push must still be followed by fresh-clone validation.

- Pragmatist thread: `019f23a2-b567-7af2-b8d3-90d5c8ebafdf`
  - receipt: `ROUND3_COUNCIL_RECEIPT`
  - verdict: `conditional-go`
  - strongest objection: current checks prove readiness to enter the release flow, not that fresh-clone and GitHub release have already succeeded.

- Critic thread: `019f23a0-bdf5-79d1-8d2d-5730a27be2ee`
  - status: `thread_not_converged`
  - action: archived and replaced; not counted as approval.

- Replacement Critic thread: `019f23a4-2d6e-7690-9ae0-78c7a4014151`
  - receipt: `ROUND3_COUNCIL_RECEIPT`
  - pre-fix verdict: `no-go`
  - post-fix receipt: `ROUND3_COUNCIL_RECEIPT_POST_FIX`
  - post-fix verdict: `conditional-go`
  - strongest objection: Round 3 had no durable receipt file and the quality gate could still pass while Round 3 evidence was incomplete.
  - note: the receipt body reported the source thread id; the actual worker thread id is recorded here from Codex thread metadata.

### Adopted Round 3 Fixes

- Add `validation/receipts/ROUND3_RELEASE_GO_NO_GO.md`.
- Make `scripts/check_structure.sh` require the Round 3 receipt file.
- Make `scripts/quality_gate.sh` require `ROUND3_COUNCIL_RECEIPT` and fail if council evidence still contains `Pending`.
- Replacement Critic post-fix verification confirmed the Round 3 receipt exists, the quality gate passes, install dry-run reports 89/89 files, cached diff has no whitespace errors, and an injected standalone `Pending.` makes the quality gate fail.
- Continue to describe the user-requested "2000-star level" as a quality target, not a verified popularity claim.

### Verdict

Conditional go for commit, merge, public repository creation, push, fresh-clone validation, and release. Public release is complete only after the pushed repository passes the same quality gate from a clean clone.
