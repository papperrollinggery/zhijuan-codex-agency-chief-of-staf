# Contributing

Keep the Skill outcome-driven under real Codex pressure: the main task should finish useful work, delegation should have a measurable benefit, and validation claims must match fresh evidence.

## Before Opening a Change

Run:

```bash
/bin/bash -p scripts/quality_gate.sh .
```

For instruction or routing changes, also run the real model smoke:

```bash
test -n "$CODEX_NATIVE_EXECUTABLE"
test -n "$CODEX_EVAL_MODEL"
test -n "$CODEX_EVAL_REASONING_EFFORT"
test -n "$CODEX_EVAL_AUTH_JSON"
test "$CODEX_EVAL_AUTH_CLASS" = dedicated -o "$CODEX_EVAL_AUTH_CLASS" = primary
test "$CODEX_EVAL_SOURCE_TRUST" = reviewed -o "$CODEX_EVAL_SOURCE_TRUST" = untrusted
/bin/bash -p scripts/model_smoke.sh \
  --root . \
  --out validation/current/model-smoke-$(/bin/date +%Y%m%d-%H%M%S) \
  --codex-executable "$CODEX_NATIVE_EXECUTABLE" \
  --model "$CODEX_EVAL_MODEL" \
  --reasoning-effort "$CODEX_EVAL_REASONING_EFFORT" \
  --skill-source verified-installed-snapshot \
  --source-trust "$CODEX_EVAL_SOURCE_TRUST" \
  --auth-json "$CODEX_EVAL_AUTH_JSON" \
  --auth-credential-class "$CODEX_EVAL_AUTH_CLASS" \
  --acknowledge-auth-readable-to-eval-process \
  --require-release-tier rc
```

The offline quality gate validates package and contract structure only. Do not describe it as model-behavior proof.
Before a release-candidate smoke, install the reviewed checkout's canonical and legacy pair with `python3 scripts/install_skill.py --force`; `verified-installed-snapshot` validates the OS-home pair with `sealed-tree-v1` before and after the run, then evaluates a clean-HOME frozen copy without touching sibling Skills. Require `tree_integrity_verified=true`, `cleanup_complete=true`, empty `cleanup_warnings`, `residual_paths`, and `cleanup_guidance`; any extra file/empty directory, internal symlink, FIFO/socket/device, non-canonical mode/owner, multi-link runtime file, or path using the reserved `.backup-`, `.staging-`, or `.failed-` prefix is release-blocking regardless of suffix validity. A bundle-root symlink is refused rather than auto-replaced. Untrusted diffs require a disposable OS user or container because same-user temp auth is readable to evaluated code.
`CODEX_NATIVE_EXECUTABLE` must be an absolute path directly to a Mach-O, ELF, or PE Codex binary. A wrapper, launcher, or symlink is rejected. macOS RC evidence additionally verifies the OpenAI Team ID signature on the main binary and `codex-code-mode-host`, executes private frozen copies, and rechecks source/copies after the suite. Unsupported publisher-attestation platforms remain release-ineligible.
Choose a `CODEX_EVAL_REASONING_EFFORT` supported by `CODEX_EVAL_MODEL`. The runner uses `--ignore-user-config`, explicitly rebinds reasoning, enables `multi_agent`, sets shell inheritance to `none`, uses OS-default helpers by absolute path, and exposes `rg` only as a checked private copy. RC review evidence permits one child and binds its spawn/start, OpenAI model/provider/effort/CLI identity, exactly one inert-wrapper `/bin/cat` full-artifact read after the final modification, the unique same-turn terminal result, and an exact author/recipient delivery after that child terminal but before the main terminal/final. The canonical worker packet contains neither a Skill slug nor a guard-read instruction; a guard is accepted only when the host independently forced the bundle load before the worker began. Wait is only used while a terminal result has not yet been delivered; it is never review truth. The reviewer terminal is a strict four-line zero-finding schema; the main final is exactly that block plus one adoption line and one isolation-disclosure line. Extra prose, repeated verdicts, or contradictory findings fail closed. A separate natural full-cycle case does not prescribe child tools: it requires the final artifact's `max(mtime, ctime)` to be strictly earlier than spawn, an exact three-line child terminal, exact delivery, and a final consisting only of that terminal plus adoption, isolation-unverified, and reviewer-read-unverified lines. It does not contribute reviewer-owned-read or cold-review proof. Requested `fork_turns:none` alone does not verify context isolation. An opaque stored spawn prompt also leaves its content, self-containment, and marker non-forwarding unverified; RC relies on the strict post-change direct-read behavior chain, while stable remains closed.

Both collaboration oracles bind the host-owned collaboration namespace, call/output/response turn metadata, started event id and bounded host timestamp, and the current `fork_turns:none` child session shape. Strict review also requires the started record between the spawn call/output and the direct read at or after started. Parent-to-child ingress must be the exact visible `NEW_TASK` header plus the bounded encrypted shape; that is syntactic binding, not authentication. It must be the first child response item, and the child action/event surface is closed to its allowlist before and after ingress. They reject malformed or duplicate deliveries, post-delivery reversals, and backdated-mtime attempts through `max(mtime, ctime)`. The reviewed cases use a closed message contract rather than open-ended semantic synonym matching: the boot receipt is exact; main progress is limited to ordered, unique `MAIN_PROGRESS:*` tokens; and strict and natural children may emit at most one exact `REVIEW_PROGRESS:*` token. Strict progress may follow a guard only after its matching output. In the clean no-memory release eval, main/child rollout response and raw event channels plus public exec JSON must each contain exactly one bound terminal/final; normal cross-channel mirrors do not double-count, while a missing or clean mirror cannot hide a dirty channel. Response assistant/delivery content must be one exact `output_text` / `input_text` block; the sole accepted child-to-parent delivery must use the current structured `FINAL_ANSWER` envelope and carry exact parent-turn metadata. Raw event messages must match the current four-key schema with `memory_citation=null` in the isolated eval home. Non-canonical, malformed, duplicate, cross-phase, cross-turn, or backdated text fails closed even when it is merely conditional. Any wait call/output must also bind the collaboration namespace and current main turn. The main task-complete must be the last rollout record.
Receipt V2 separates artifact evidence from credential assurance. Primary or a declared dedicated credential may support RC evidence for reviewed source only when all 20 smoke cases pass, the signed execution copy and per-case rollout identity match, required strict-review and natural-completion chains pass, private case state is outside the project parent, the global pair and every frozen installed snapshot remain `sealed-tree-v1` clean, runner/cases/runtime and the imported installer helper remain byte-bound, the dedicated full `.git` manifest is unchanged, auth files remain unchanged, and exact auth values do not appear in output. The receipt exposes `installer_sha256`; installer drift after the initial snapshot fails the run. This proves only the reviewed smoke scope; Goal lifecycle, real task/thread ThreadOps, cold-context isolation, and host plugin/app compatibility remain explicitly untested. It also does not verify low privilege, eval-only use, or OS/container isolation; `operational_credential_safety.verified` remains false. Stable additionally requires verified review-context isolation, zero untested capabilities, and authoritative workload-identity assurance. Exit 0, content hash alone, CLI config acceptance, stderr text, or an unsigned JWT claim cannot substitute for those fields.

## Change Rules

- Keep `SKILL.md` focused on core routing and operating rules.
- Put detailed procedures in `references/`.
- Put deterministic repeated logic in `scripts/`.
- Put machine-only evidence shapes in `assets/`; keep ordinary user output in natural language.
- Do not add secrets, personal account data, or machine-specific paths.
- Do not add an `AGENTS.md` routing installer or require `AGENTS.md` injection for activation.
- Keep `agency-chief-of-staff` as the canonical explicit/best-effort-implicit entrypoint; keep `zhijuan-codex-agency-chief-of-staf` explicit-only and generated from the same source.
- Do not claim implicit selection is guaranteed: host skill context budgets and selection policy can exclude a description. Recommend explicit canonical invocation, never `AGENTS.md` routing injection, when deterministic startup matters.
- Do not count a real Codex task/thread as complete without tool id/readback, artifact verification, adoption, and cleanup state.
- Count every collaboration lifecycle attempt, including started-only, failed, and cancelled calls. `collaboration=none` means zero attempts.
- Do not accept an RC reviewer result without a uniquely rollout-bound spawn/start/child-terminal/direct-read/delivery chain, matching child execution identity and turn id, exactly one inert-wrapper full-file direct-read action after the final modification, one terminal result, one exact no-blocker verdict, and explicit main-thread adoption. If a wait was needed, its bounded call/output pair must precede the bound delivery, but wait is optional and never review truth. A plaintext packet must also prove the runtime-random marker was absent. When the stored packet is opaque, record prompt content/self-containment/marker non-forwarding as unverified and do not use the token format as evidence. Main-thread reads, extra actions, expressions, substring matches, decoders, intermediate reviewer prose, negative verdicts, and generic wait completion are not tool evidence. Do not call it verified cold review unless context isolation and marker non-forwarding are also proven; a requested isolation parameter is not proof.
- Keep worker packet labels ordered, unique, and non-empty; a multi-line field is valid only when content appears before the next required label. Default packets contain neither a Skill slug nor a guard request. If the host independently forces a worker guard, it may read zero or one matching bundle only as the first stable tool attempt through `cat`, one complete `sed` range, or bounded contiguous `sed` chunks whose aggregate output exactly matches the full file; any gap, side effect, partial, failed, retried, wildcard, wrong, or dual-bundle touch is a failure and never counts as activation.
- If the host requires a pre-read Skill-use announcement, keep the exact canonical or generated-legacy template; do not freely restate task scope. Allow at most one additional Skill-location recovery notice and no business/collaboration tool before the expected bundle is successfully read and booted.

## Review Standard

A change is ready when it improves one of these:

- Lower friction for first-time users.
- Better target-to-delivery completion.
- Lower context and ceremony cost.
- Better native subagent or real task/thread boundaries.
- Better current, falsifiable validation confidence.
