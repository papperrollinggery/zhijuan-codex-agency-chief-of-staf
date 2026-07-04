# Domain Deliverable Gates

Thread convergence proves process. It does not prove that a creative, storyboard, proposal, research, copy, story, execution, or planning deliverable is professionally usable.

For those task types, the Chief-of-Staff must require a `DOMAIN_DELIVERABLE_RECEIPT` before claiming client-ready or release-ready quality.

## Required Receipt

Use `assets/DOMAIN_DELIVERABLE_RECEIPT_TEMPLATE.yaml`.

Required evidence:

- `deliverable_type`: one of `creative`, `storyboard`, `proposal`, `research`, `copy`, `story`, `execution_plan`, or `planning`.
- `audience`: who will read or use the output.
- `brief_trace`: source refs, preserved requirements, assumptions, and explicit exclusions.
- `artifacts`: concrete files or deliverables, each with role and status.
- `domain_quality_gates`: client language, source-brief preservation, storyboard/shot logic, asset/reference trace, and evidence/source trace.
- `validation`: commands or manual review evidence.
- `review_status`: at least `cold_reviewed` plus domain review before `verdict: PASS`.

## Hard Rules

1. `VALIDATION=PASS`, a green script, or a worker `WORKER_RECEIPT` does not equal domain quality PASS.
2. A thread receipt without `DOMAIN_DELIVERABLE_RECEIPT` can be adopted as process evidence, not as client-ready evidence.
3. If the task is creative/storyboard/proposal/research/copy/story/execution/planning and final wording says `client-ready`, `可交付`, `release-ready`, `ready to send`, or equivalent, a domain receipt is required.
4. A client-ready claim also requires `verdict: PASS`, `review_status: cold_reviewed_and_domain_reviewed`, at least one passing domain gate, and no failing domain gates.
5. `verdict: PASS` is invalid when `review_status` is `not_reviewed`.
6. Missing `brief_trace` or empty `artifacts` blocks release/adoption, even if tests passed.
7. For visual or media work, the asset/reference trace can be a C2PA-like or OpenAssetIO-like manifest field; full signature infrastructure is not required for this Skill.

## Minimal Adoption Rule

The Chief-of-Staff may adopt a partial domain receipt only as `NEEDS_HUMAN` or `FAIL`. It must not rewrite the status to PASS.
