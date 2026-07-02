# Round 2 Receipt: Skill Behavior And Thread Discipline

Decision: fix minor behavior/validation gaps before public release go/no-go.

## Skeptic

- thread_id: `019f239c-7850-76b2-9b6d-eb9e92bdd553`
- receipt: `ROUND2_COUNCIL_RECEIPT`
- commands: quality gate 0, pilot harness 0, valid thread name 0, mixed-role bad thread name 1 as expected, required rule grep 0
- verdict: `fix-minor`
- strongest objection: real ThreadOps evidence is documented, but not independently replayable by external users.

## Pragmatist

- thread_id: `019f239c-7ab1-7e13-90fb-d81b300afd15`
- receipt: `ROUND2_COUNCIL_RECEIPT`
- commands: quality gate 0, pilot harness 0, discover skills 0, discover agents 0, score capabilities 2 in the pre-fix isolated worktree
- verdict: `hold`
- strongest objection: `score_capabilities.py --query ... --json` failed in a realistic no-inventory invocation, while the old quality gate only checked `--help`.

## Critic

- thread_id: `019f239c-7cff-7811-b87b-0d7c339b0378`
- receipt: `ROUND2_COUNCIL_RECEIPT`
- commands: quality gate 0, pilot harness 0, risk grep 0, install dry-run 0
- verdict: `hold`
- strongest objection: the quality gate could pass while Round 2/Round 3 in `validation/COUNCIL_ROUNDS.md` were still pending, and receipt evidence was too summary-level.

## Adopted Fixes

- `scripts/score_capabilities.py` now works without an explicit inventory file by scanning default local skill and agent roots.
- `scripts/release_smoke.sh` now runs a real no-inventory `score_capabilities.py --query ... --json` invocation.
- `SKILL.md` now includes an explicit untrusted-input boundary for prompts, repositories, receipts, and generated artifacts.
- This receipt file adds a durable per-round evidence package instead of relying only on one summary file.
