# Audit Review Backend Step 4B

Step 4B adds deterministic audit checks and scoring on top of the normalized `audit_trail_record` rows extracted in Step 4A.

This step does not call Veeva directly. It does not use AI. It does not add frontend screens, scheduler behavior, approval workflow, or PDF/report generation.

## New Statuses

Audit review jobs now support:

- `ANALYZING`
- `ANALYZED`

The analyze flow accepts jobs in `EXTRACTED` or `ANALYZED` state. Re-running analysis on an `ANALYZED` job clears prior findings and scores for that job before recalculating.

## Endpoints

Run deterministic analysis:

```http
POST /audit-review-jobs/{job_id}/analyze
```

Request body is optional. Defaults are used when omitted:

```json
{
  "business_timezone": "Asia/Kolkata",
  "business_start_hour": 9,
  "business_end_hour": 18
}
```

Fetch findings:

```http
GET /audit-review-jobs/{job_id}/findings?severity=HIGH&check_code=MISSING_USER_ID&limit=100
```

All query parameters are optional. Findings return safe traceability evidence only and do not include `raw_payload_json`.

Fetch score rows:

```http
GET /audit-review-jobs/{job_id}/scores
```

The response includes one row per deterministic check plus an `OVERALL` row.

Job detail now includes:

- `finding_count`
- `overall_score`
- `rating`
- `analysis_summary_json`

## Checks

### MISSING_USER_ID

Flags records where `user_id` is null, blank, or `unknown`.

- Severity: `HIGH` when `action_type` indicates delete/remove/purge/permission/role/access/security; otherwise `MEDIUM`
- Penalty: 5 per finding, capped at 15

### MISSING_TIMESTAMP

Flags records where `event_timestamp` is null.

- Severity: `HIGH`
- Penalty: 10 per finding, capped at 20

### DELETE_ACTION

Flags records where `is_delete_action = true` or `action_type` contains delete/remove/purge.

- Severity: `HIGH` when `object_type` or `action_type` indicates critical config/security/user/permission context; otherwise `MEDIUM`
- Penalty: 2 per finding, capped at 20

### PERMISSION_ACCESS_CHANGE

Flags records where `is_permission_change = true`, or where `action_type`, `object_type`, or `field_name` contains role/permission/access/security/group/profile/user_role.

- Severity: `HIGH`
- Penalty: 8 per finding, capped at 25

### OFF_HOURS_ACTIVITY

Flags records where `event_timestamp` falls outside configured business hours.

- Default business window: `09:00` to `18:00` in `Asia/Kolkata`
- Severity: `MEDIUM` for delete or permission/access changes; otherwise `LOW`
- Penalty: 1 per finding, capped at 10

## Scoring

Overall score starts at 100. Each check applies its capped penalty. Final score cannot go below 0.

Ratings:

- 90 to 100: `COMPLIANT`
- 75 to 89: `MINOR_FINDINGS`
- 60 to 74: `MAJOR_FINDINGS`
- Below 60: `CRITICAL_RISK`

## Finding Evidence

Finding evidence contains safe traceability only:

```json
{
  "record_id": "...",
  "source_record_key": "...",
  "event_timestamp": "...",
  "user_id": "...",
  "user_name": "...",
  "action_type": "...",
  "object_type": "...",
  "object_id": "...",
  "object_name": "...",
  "field_name": "..."
}
```

Full Veeva raw payloads are intentionally excluded from findings.
