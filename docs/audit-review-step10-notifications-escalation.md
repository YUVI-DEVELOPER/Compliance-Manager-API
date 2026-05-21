# Audit Review Step 10: Notifications & Escalation

Step 10 adds in-app notification records for Veeva Audit Trail Periodic Review reports. It does not modify the Veeva MCP server, use AI, expose raw audit payloads, approve reports, or remediate findings.

## Escalation Matrix

| Rating | Notification type | Priority | Stakeholders | Required action |
| --- | --- | --- | --- | --- |
| COMPLIANT | AUDIT_REVIEW_COMPLIANT | LOW | System Owner | Document and close. Schedule next review. |
| MINOR_FINDINGS | AUDIT_REVIEW_MINOR_FINDINGS | MEDIUM | QA Manager, IT Compliance | Observation report; CAPA within 30 days. |
| MAJOR_FINDINGS | AUDIT_REVIEW_MAJOR_FINDINGS | HIGH | QA Director, Regulatory Affairs | Formal CAPA + Deviation; escalate in 7 days. |
| CRITICAL_RISK | AUDIT_REVIEW_CRITICAL_RISK | CRITICAL | VP Quality, Executive Leadership, Regulatory Authority | Immediate escalation; system suspension review. |

## Data Model

The `audit_review_notification` table stores one notification per report, escalation role, and notification type.

Each row links to:

- `audit_review_report.report_id`
- `audit_review_job.job_id`
- `asset_basic_info.asset_id`

Statuses are `PENDING`, `READY`, `SENT`, `FAILED`, and `DISMISSED`. Delivery channels are `IN_APP`, `EMAIL`, and `BOTH`.

## Endpoints

- `POST /audit-review-reports/{report_id}/prepare-notifications`
- `GET /audit-review-reports/{report_id}/notifications`
- `POST /audit-review-notifications/{notification_id}/send`
- `POST /audit-review-reports/{report_id}/send-notifications`
- `GET /asset/{asset_id}/audit-review-notifications?status=&priority=&limit=`
- `POST /audit-review-notifications/{notification_id}/dismiss`

Prepare request:

```json
{
  "requested_by": "qa.manager@example.com",
  "regenerate": false,
  "delivery_channel": "IN_APP"
}
```

Send request:

```json
{
  "sent_by": "qa.manager@example.com"
}
```

Dismiss request:

```json
{
  "dismissed_by": "qa.manager@example.com",
  "reason": "Handled outside system"
}
```

## In-App Behavior

Preparing notifications reads the report rating and creates role-specific `READY` notification records from the escalation matrix. Existing notifications for the same report, recipient role, and type are reused unless `regenerate=true`.

When `regenerate=true`, previous `PENDING` or `READY` rows for that report/type are marked `DISMISSED` with regeneration metadata, then new rows are created.

Sending an `IN_APP` notification marks it `SENT` and sets `sent_dt`.

## Email Fallback

No app-wide email service is currently present. `EMAIL` and `BOTH` delivery requests are controlled safely:

- The workflow does not crash.
- No fake “email sent” result is returned.
- The notification remains available in-app.
- The response message is: `Email delivery is not configured. Notification is available in-app.`

## UI Behavior

The Audit Review report view now includes a `Notifications & Escalation` panel. It shows:

- escalation priority badge
- report rating
- required action
- stakeholder roles
- notification status summary
- prepare and send buttons
- notification history table

For non-approved reports, the UI clearly displays: `Notifications for non-approved reports are draft/preliminary.`

## Security Rules

- Notification messages do not include `raw_payload_json`.
- Veeva credentials, session IDs, and authorization tokens are not included.
- Report approval remains manual.
- Notifications do not trigger remediation.
- Missing email configuration does not break report, scheduler, or manual review flows.

## Testing Steps

1. Apply Alembic migration `20260428_0030_add_audit_review_notifications`.
2. Generate or open an audit review report.
3. Call `POST /audit-review-reports/{report_id}/prepare-notifications`.
4. Confirm returned notifications include `report_id`, `job_id`, and `asset_id`.
5. Confirm response text does not contain `raw_payload_json`.
6. Call `GET /audit-review-reports/{report_id}/notifications`.
7. Call `POST /audit-review-notifications/{notification_id}/send` for an `IN_APP` notification and confirm status becomes `SENT`.
8. Call `POST /audit-review-reports/{report_id}/send-notifications`.
9. Call `GET /asset/{asset_id}/audit-review-notifications`.
10. Optionally call `POST /audit-review-notifications/{notification_id}/dismiss`.
11. Run the updated `Veeva_Audit_Review_Module.postman_collection.json` notification requests.
