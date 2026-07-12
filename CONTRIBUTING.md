# Contributing

Keep the Skill outcome-driven under real Codex pressure: the main task should finish useful work, delegation should have a measurable benefit, and validation claims must match fresh evidence.

## Before Opening a Change

Run:

```bash
bash scripts/quality_gate.sh .
```

For instruction or routing changes, also run the real model smoke:

```bash
python3 scripts/run_model_evals.py \
  --root . \
  --out validation/current/model-smoke-$(date +%Y%m%d-%H%M%S) \
  --auth-json "$CODEX_EVAL_AUTH_JSON" \
  --auth-credential-class dedicated \
  --acknowledge-auth-readable-to-eval-process
```

The offline quality gate validates package and contract structure only. Do not describe it as model-behavior proof.
Run model smoke only from a reviewed checkout with a dedicated low-privilege credential; untrusted diffs require a disposable OS user or container because same-user temp auth is readable to evaluated code.

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
