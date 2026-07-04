# Release Convergence Receipt

Machine-readable source: `validation/release_receipt.json`.

This receipt is the single release table for dispatch, adoption or rejection, cleanup, and review verdicts. Worker receipts and council notes are supporting evidence only; release readiness is decided from this consolidated artifact plus the validators.

| Thread | Class | Wave | Receipt | Adoption | Cleanup | Verdict |
|---|---|---:|---|---|---|---|
| `019f23be-a188-7402-968e-f223d32e4419` | scout worker | - | received | adopted | archived | n/a |
| `019f23be-a3a0-7a60-9849-419ec1424b46` | agent scout worker | - | received | adopted | archived | n/a |
| `019f23bf-ed5b-7c61-9f44-b3fc2c41825a` | implementation worker | - | received | adopted | archived | n/a |
| `019f23c6-cec3-7ad2-a68b-2bb16f9ef8b0` | review worker | 1 | received | adopted | archived | PASS |
| `019f23a0-bdf5-79d1-8d2d-5730a27be2ee` | review worker | 2 | missing | rejected | archived | thread_not_converged; bounded rescue |
| `019f23a4-2d6e-7690-9ae0-78c7a4014151` | review worker | 2 | received | adopted after fix | archived | conditional-go |

Release review budget:

- `max_review_waves`: 2
- `max_parallel_reviewers_per_deliverable`: 2
- `review_receipt_poll_limit`: 3
- Every added review wave requires `add_review_wave_reason`.
- After one cold review and one domain or rebuttal review converge, stop adding reviewers unless `additional_review_wave_reason` explains why the current evidence is insufficient.

Stuck review rule:

- No reviewer receipt within the poll limit becomes `thread_not_converged`.
- Cleanup must be `archived` or `cleanup_blocked`.
- A bounded rescue reviewer must be recorded with `rescue_thread_id`.
