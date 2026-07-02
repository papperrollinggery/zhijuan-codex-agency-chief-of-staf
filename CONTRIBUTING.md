# Contributing

Keep the skill useful under real Codex pressure: small tasks should stay small, long tasks should keep receipts, and thread failures should be recoverable.

## Before Opening a Change

Run:

```bash
bash scripts/quality_gate.sh .
```

For instruction changes, also run a local pilot:

```bash
python3 scripts/pilot_harness.py --root . --out /tmp/agency-thread-pilot
```

## Change Rules

- Keep `SKILL.md` focused on core routing and operating rules.
- Put detailed procedures in `references/`.
- Put deterministic repeated logic in `scripts/`.
- Put reusable packet or prompt shapes in `assets/`.
- Do not add secrets, personal account data, or machine-specific paths.
- Do not count a Codex Thread as complete without a receipt or a recorded `thread_not_converged` rescue.

## Review Standard

A change is ready when it improves one of these:

- Lower friction for first-time users.
- Better task classification.
- Better thread receipt and cleanup discipline.
- Better rescue behavior.
- Better validation confidence.
