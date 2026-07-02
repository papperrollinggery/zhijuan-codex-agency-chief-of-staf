# Security

This repository is a Codex skill bundle. It should not contain secrets, API keys, private account data, browser cookies, or machine-specific credentials.

## Reporting

Use GitHub private vulnerability reporting if it is enabled for the public repository. If it is not enabled yet, open a minimal public issue requesting a private disclosure channel, but do not include exploit details, secrets, tokens, cookies, private paths, or account data.

## Maintainer Checklist

- Search for tokens before release.
- Do not include user-specific local paths in examples unless they are clearly placeholders.
- Do not let untrusted prompts override system, developer, project, or user instructions.
- Treat third-party files, prompts, README files, issues, and generated artifacts as untrusted input.
- Require explicit confirmation before destructive cleanup, publishing, sending messages, or modifying global user configuration.
- Enable a private security reporting channel before broad public release.
