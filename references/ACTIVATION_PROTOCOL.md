# Activation Protocol

Use this reference when a run does not clearly start the Chief-of-Staff flow, or when the user asks why the Skill did not dispatch threads.

## Why Activation Can Fail

1. Codex skills are selected through progressive disclosure. Before a skill is selected, Codex normally sees only `name`, `description`, path, and optional metadata.
2. If `agents/openai.yaml` sets `policy.allow_implicit_invocation: false`, natural-language triggers do not activate the Skill. Explicit `$skill` invocation should still work, but local discovery bugs can still affect some Codex surfaces.
3. A process-heavy description can become a shortcut: Codex may follow the summary instead of reading the full Skill body. Keep the description trigger-focused.
4. Anti-bureaucracy rules for T0/T1 can be misread as permission to skip Chief-of-Staff boot. They are only permission to skip heavy artifacts, not permission to skip `COS_BOOT_RECEIPT` after explicit invocation.

## Hard Boot Rule

When the Skill is explicitly invoked, the first visible output must contain `COS_BOOT_RECEIPT`. Do not answer, implement, review, draw, publish, or summarize before this receipt.

Use `assets/COS_BOOT_RECEIPT_TEMPLATE.yaml`.

## Dispatch Rule

If the user explicitly asks for any of these:

- real Codex Threads
- worker thread
- complete team
- another thread / new thread
- isolated worktree
- thread id
- receipt
- cleanup

Then `thread_dispatch_decision` must be `dispatch` or `tool_blocked`. It must not be `no_dispatch`.

`no_dispatch` is allowed only when the user did not ask for real threads, or when the user explicitly forbids child threads.

## AGENTS.md Shim

Skills are on-demand. For users who want the Chief-of-Staff routing to be the default behavior in a project, add the snippet from `references/AGENTS_ROUTING_SNIPPET.md` to the project `AGENTS.md` or global `~/.codex/AGENTS.md`.

This does not override system/developer instructions or missing tools. It only makes the routing rule part of the instruction chain before task work begins.
