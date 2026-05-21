# Audit Review Step 9: Periodic Scheduler

## Overview

Step 9 adds durable scheduling for Veeva Audit Trail Periodic Review candidates. A schedule belongs to an asset and stores the Veeva candidate metadata, frequency, review window, timezone, business hours, next run timestamp, last run timestamp, and last generated job.

The scheduler automates the full report workflow:

1. Create audit review job.
2. Extract Veeva audit trail records through the existing MCP client.
3. Run deterministic audit review checks.
4. Generate a draft audit review report.
5. Submit the generated report for review.
6. Approve the generated report with scheduler approval metadata.
7. Persist a scheduler run log.

It does not dispatch notifications or perform remediation.

## Tables

- `audit_review_schedule`: one configured periodic review candidate for an asset.
- `audit_review_schedule_run`: immutable run history for STARTED, COMPLETED, FAILED, and SKIPPED scheduler attempts.

Run logs store safe execution summaries only. Raw Veeva payloads and credentials are not exposed by schedule APIs.

## API Endpoints

- `POST /asset/{asset_id}/audit-review-schedules`
- `GET /asset/{asset_id}/audit-review-schedules`
- `PATCH /audit-review-schedules/{schedule_id}`
- `POST /audit-review-schedules/{schedule_id}/run-now`
- `POST /audit-review-scheduler/run-due`
- `GET /audit-review-schedules/{schedule_id}/runs`

`run-now` triggers one schedule immediately. `run-due` processes all enabled schedules where `next_run_dt <= now()`.

## Review Period Logic

For each run:

- `review_end_dt` is the current UTC time.
- `review_start_dt` is the last completed scheduler review end time.
- If no completed run exists, `review_start_dt = review_end_dt - review_window_days`.
- If `review_window_days` is null, the service derives a conservative window from frequency.

The generated audit review job uses `period_basis = SCHEDULED` and `trigger_mode = SCHEDULED_DUE` or `SCHEDULED_MANUAL`.

## Frequency Logic

After an attempt, if the schedule was due, `next_run_dt` advances from the existing scheduled anchor until it is in the future:

- DAILY: +1 day
- WEEKLY: +7 days
- MONTHLY: next month, same day where possible
- QUARTERLY: +3 months
- HALF_YEARLY: +6 months
- ANNUAL: +12 months

Timezone-aware datetimes are used. The default scheduler timezone is `Asia/Kolkata`.

## Duplicate And Concurrency Controls

- A schedule run is persisted as STARTED before the extraction workflow begins.
- A partial unique index prevents more than one active STARTED run per schedule.
- A concurrent run is SKIPPED while another non-stale STARTED run exists.
- STARTED runs older than six hours are marked FAILED as stale before retry.
- The scheduler checks for an existing job with the same asset, audit trail type, and review period before creating a new job.

## Automatic Approval

The scheduled workflow submits and approves the generated report automatically through the same report transition services used by the manual endpoints. The approval history records the scheduler actor, submission notes, reviewer comments, and timestamps.

## Production Deployment

The API starts an in-process scheduler loop by default. While the FastAPI backend is running, it periodically calls the same due-run service used by:

```text
POST /audit-review-scheduler/run-due
```

Scheduler loop settings:

```text
AUDIT_REVIEW_SCHEDULER_ENABLED=true
AUDIT_REVIEW_SCHEDULER_INTERVAL_SECONDS=60
AUDIT_REVIEW_SCHEDULER_INITIAL_DELAY_SECONDS=10
VEEVA_AUDIT_EXTRACTION_CHUNK_DAYS=14
VEEVA_AUDIT_LOOKBACK_DAYS=30
```

Recommended production assumptions:

- Keep exactly one API worker or scheduler caller active when possible. Database guards reduce duplicate active runs, but one scheduler owner is clearer operationally.
- Increase `AUDIT_REVIEW_SCHEDULER_INTERVAL_SECONDS` if production should poll less often.
- Protect the endpoint with the deployment's admin authentication layer.
- Monitor FAILED schedule runs and backend logs.
- Keep `VEEVA_AUDIT_EXTRACTION_CHUNK_DAYS` at or below the Vault range that reliably returns audit data; scheduled monthly, quarterly, half-yearly, and annual reviews are chunked and merged before checklist analysis.
- Keep `VEEVA_AUDIT_LOOKBACK_DAYS` aligned to the target Vault audit endpoint's available lookback window. The extractor fails fast with a clear message when a requested period is older than this window; it does not clamp scheduled review periods.

## Known Limitations

- No notifications are sent for failed runs in Step 9.
- No remediation workflow is started.
- No AI/LLM analysis is used.
- Backfill/catch-up is conservative: missed intervals advance to the next future schedule after a run attempt.
- The scheduler depends on the existing Veeva MCP extraction path and inherits its availability.

## Testing Steps

1. Run Alembic migration `20260428_0029_add_audit_review_scheduler`.
2. Start the existing Veeva MCP server.
3. Start the Compliance Manager API.
4. Create a schedule with `POST /asset/{asset_id}/audit-review-schedules`.
5. Confirm the schedule appears in `GET /asset/{asset_id}/audit-review-schedules`.
6. Trigger `POST /audit-review-schedules/{schedule_id}/run-now`.
7. Verify a job was created, extracted, analyzed, and has an APPROVED report.
8. Verify the scheduled report is APPROVED automatically.
9. Set `next_run_dt` to a past timestamp and call `POST /audit-review-scheduler/run-due`.
10. Confirm `GET /audit-review-schedules/{schedule_id}/runs` shows run history.
11. Confirm manual audit review job creation, extraction, analysis, report generation, and QA approval still work.
