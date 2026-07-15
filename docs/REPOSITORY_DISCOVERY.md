# Repository discovery and release metadata

> Status: proposed metadata for the next authorized public update
>
> Verified public state: 2026-07-15
>
> Read-only evidence: GitHub repository API fields `description`, `homepageUrl`, and `repositoryTopics`, plus the public Releases API for stable/prerelease tags; observed values are recorded below and may drift after this date.
>
> Evidence boundary: this file prepares discoverability metadata; it does not apply GitHub settings, publish the current checkout, or claim search-ranking impact.

## Current public state

Before this authorized update, the public GitHub repository reported no About description, website, or topics. Its latest stable release remains `v0.1.7`; this checkout is the reviewed `v0.2.0-rc.3` release source. Public description, topics, tag, and release still require post-write API readback before they count as published.

GitHub documents topics as a discovery mechanism for finding repositories by purpose and subject. Topic names must use lowercase letters, numbers, and hyphens, be at most 50 characters, and a repository may have at most 20. Applying repository metadata is an external write and requires maintainer authorization and working GitHub authentication.

## Proposed GitHub About metadata

Description:

> Outcome-owned Codex Skill for multi-agent research, planning, execution, model routing, verification, cold review, and release-ready delivery.

Website: leave unset until there is a maintained project site. Do not use a local validation artifact or an unpublished branch URL.

Suggested topics:

- `codex`
- `openai`
- `codex-cli`
- `codex-desktop`
- `codex-skill`
- `ai-agents`
- `multi-agent`
- `agent-orchestration`
- `subagents`
- `model-routing`
- `cold-review`
- `developer-tools`
- `python`

These values describe the project without claiming native custom-agent selection, cross-host portability, Claude availability, stable release status, or measured cost savings.

## LLM and generative-search index

The root [`llms.txt`](../llms.txt) is a concise, human-readable and machine-readable index following the emerging `llms.txt` proposal. It links only to source-of-truth Markdown and the public Releases surface, names the canonical and legacy entry boundaries, and states that Claude/Fable are optional and disabled by default.

`llms.txt` is a proposal, not a ranking guarantee or crawler-control file. Keep it concise, keep every linked path valid, and update it whenever the canonical entry, release boundary, documentation map, or provider policy changes. `robots.txt`, licensing, and repository visibility remain separate concerns.

## Authorized publish checklist

1. Re-run the current release gates and independent review from the exact commit to publish.
2. Confirm the README version table, changelog, `llms.txt`, release notes, and tagged source agree.
3. With fresh maintainer authorization and valid GitHub authentication, apply the proposed description and topics.
4. Read back the public About panel and topics; do not treat a successful API request alone as proof.
5. Publish or update the release only after the commit, tag, assets, and release notes are mutually consistent.

## Sources

- [GitHub Docs: Classifying your repository with topics](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics)
- [GitHub Docs: Best practices for repositories](https://docs.github.com/en/repositories/creating-and-managing-repositories/best-practices-for-repositories)
- [`llms.txt` proposal and format](https://llmstxt.org/)
