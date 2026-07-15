# Contributing

Keep the Skill outcome-driven under real Codex pressure: the main task should finish useful work, delegation should have a measurable benefit, and validation claims must match fresh evidence.

## Before Opening a Change

Run:

```bash
bash scripts/quality_gate.sh .
```

For instruction or routing changes, also run the real model smoke:

```bash
export CODEX_EVAL_CODEX=/absolute/path/to/codex
export CODEX_EVAL_MODEL='<exact-current-openai-judgment-model>'
export CODEX_EVAL_REASONING_EFFORT='<supported-effort>'
export CODEX_EVAL_CATALOG=/absolute/path/current-catalog.json
export CODEX_EVAL_STATE_DB="$HOME/.codex/state_5.sqlite"
export CODEX_EVAL_THREAD_ID='<requested-root-task-id>'
export CODEX_EVAL_CATALOG_CWD="$PWD"
export CODEX_EVAL_AUTH_JSON=/path/to/dedicated-eval-auth.json
export CODEX_EVAL_AUTH_CLASS=dedicated

python3 -I -S scripts/run_model_evals.py \
  --root . \
  --out validation/current/model-smoke-$(date +%Y%m%d-%H%M%S) \
  --codex-executable "$CODEX_EVAL_CODEX" \
  --model "$CODEX_EVAL_MODEL" \
  --reasoning-effort "$CODEX_EVAL_REASONING_EFFORT" \
  --catalog "$CODEX_EVAL_CATALOG" \
  --catalog-state-db "$CODEX_EVAL_STATE_DB" \
  --catalog-thread-id "$CODEX_EVAL_THREAD_ID" \
  --catalog-cwd "$CODEX_EVAL_CATALOG_CWD" \
  --auth-json "$CODEX_EVAL_AUTH_JSON" \
  --auth-credential-class "$CODEX_EVAL_AUTH_CLASS" \
  --acknowledge-auth-readable-to-eval-process
```

The equivalent checked entrypoint is `make model-smoke`; it consumes the same variables and fails before starting Python if any required value is absent. If the catalog belongs to a non-default Codex home, export `CODEX_HOME`; the Make target then adds `--catalog-codex-home "$CODEX_HOME"`.

The auth-bearing runner must be launched with `python3 -I -S`. Before repository-local imports it verifies the complete no-follow `scripts/` tree against clean `HEAD`, including ignored bytecode, extension, package, symlink, and directory entries. Hardened Git reads disable replacement objects, reject non-`H` index flags, and bind every evaluated runtime file to its real non-replaced `HEAD` blob; Codex and tool-shell `PATH` values are pinned to system binaries. Process cleanup covers the original process group, not a same-user child that creates a new session, so hostile evaluations still require a disposable OS user or container.

The offline quality gate validates package and contract structure only. Do not describe it as model-behavior proof.
Run model smoke only from a reviewed checkout with a dedicated low-privilege credential; untrusted diffs require a disposable OS user or container because same-user temp auth is readable to evaluated code.
Git-bound release evidence requires Git 2.45+ so the explicit global `--no-lazy-fetch` guard is available; older clients fail closed.
Even a passing run is portable prerelease evidence only when the dedicated credential and fresh live catalog/state/task binding are verified by the receipt. A primary credential or an unverified binding remains diagnostic and is not release evidence.

## Change Rules

- Keep `SKILL.md` focused on core routing and operating rules.
- Put detailed procedures in `references/`.
- Put deterministic repeated logic in `scripts/`.
- Put machine-only evidence shapes in `assets/`; keep ordinary user output in natural language.
- Do not add secrets, personal account data, or machine-specific paths.
- Do not add an `AGENTS.md` routing installer or require `AGENTS.md` injection for activation.
- Do not count a real Codex task/thread as complete without tool id/readback, artifact verification, adoption, and cleanup state.

## Review Standard

A change is ready when it improves one of these:

- Lower friction for first-time users.
- Better target-to-delivery completion.
- Lower context and ceremony cost.
- Better native subagent or real task/thread boundaries.
- Better current, falsifiable validation confidence.
