## Summary

Describe the user-visible problem and the smallest change that addresses it.

## Scope

- Files or behavior changed:
- Intentionally not changed:
- Compatibility or release claims introduced: none, or list each claim with evidence.

## Verification

List actual commands and results. A green offline gate does not by itself prove model, reviewer, native task/thread, cross-host, or stable-release behavior.

| Check | Result | What it proves |
| --- | --- | --- |
| `bash scripts/quality_gate.sh .` | Not run | Offline package/contract checks only |
| `git diff --check` | Not run | Patch whitespace only |

If an item was not run, keep it marked as not run and explain why.

## Review checklist

- [ ] The change is limited to the stated problem.
- [ ] New or changed relative links resolve from their source files.
- [ ] Any changed YAML, JSON, TOML, or other structured files were parsed by an appropriate validator.
- [ ] No credentials, auth files, private account data, private paths, or unredacted private logs are included.
- [ ] Documentation distinguishes current evidence from historical notes and future intent.
- [ ] Claims are limited to the checks that were actually run.
- [ ] Instruction or routing changes include current model-behavior evidence, or explicitly state that it was not run.
- [ ] No `AGENTS.md` routing installer or implicit modification was added.
- [ ] Publishing, tagging, pushing, or other external writes are not inferred from this pull request.

## Residual risk

List remaining uncertainty, host-specific limits, and checks intentionally deferred.
