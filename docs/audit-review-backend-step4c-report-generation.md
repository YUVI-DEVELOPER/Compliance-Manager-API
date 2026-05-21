# Audit Review Backend Step 4C - Draft Report Generation

Step 4C generates a deterministic draft audit review report from an analyzed audit review job. It does not call Veeva, does not use AI/LLM, does not generate PDFs, and does not approve the report.

## Status Flow

- Report generation is allowed only when the job status is `ANALYZED` or `REPORT_DRAFTED`.
- During generation, the job status is set to `REPORT_GENERATING`.
- On success, the job status is set to `REPORT_DRAFTED`.
- The new report row is created with report status `DRAFT`.
- Existing `DRAFT` reports for the same job are marked `SUPERSEDED` before the new draft is created.

## Endpoints

```http
POST /audit-review-jobs/{job_id}/generate-report
GET /audit-review-reports/{report_id}
GET /asset/{asset_id}/audit-review-reports
GET /audit-review-jobs/{job_id}
```

`GET /audit-review-jobs/{job_id}` now includes:

- `latest_report_id`
- `latest_report_status`
- `report_summary_json`

## Stored Report

Reports are stored in `audit_review_report`.

- Structured report JSON is stored in `report_payload_json` and returned as `report_json`.
- Markdown is stored in `report_markdown`.
- Summary values are stored in `report_summary_json` and copied to `audit_review_job.report_summary_json`.

## Report JSON Shape

The report includes:

- `title`
- `asset`
- `review_scope`
- `execution_summary`
- `finding_summary`
- `check_summary`
- `key_findings`
- `recommendations`
- `system_notes`

Key findings include deterministic finding title/summary and traceability through `record_id` and `source_record_key` only. Raw audit payloads are not included.

## Markdown Sections

The markdown draft includes:

1. Executive Summary
2. Review Scope
3. Compliance Score Summary
4. Findings Summary
5. Key Findings
6. Recommendations
7. Reviewer Notes
8. System Notes

## Security Notes

- Raw Veeva audit payloads are not loaded into the report generator.
- Veeva credentials and session IDs are not stored or returned.
- The report is always `DRAFT`.
- AI was not used for this step.
- Human QA/Compliance review is required before approval.

## Example Postman Requests

Generate report:

```http
POST {{base_url}}/audit-review-jobs/{{job_id}}/generate-report
```

Get report by ID:

```http
GET {{base_url}}/audit-review-reports/{{report_id}}
```

List reports for asset:

```http
GET {{base_url}}/asset/{{asset_id}}/audit-review-reports
```

Get job after report generation:

```http
GET {{base_url}}/audit-review-jobs/{{job_id}}
```

## Route Verification

From `v_API`, verify the backend route table without needing a browser:

```powershell
@'
from app.main import app
for route in app.routes:
    methods = getattr(route, "methods", None)
    path = getattr(route, "path", "")
    if "audit-review" in path:
        print(f"{','.join(sorted(methods or [])):12} {path}")
'@ | .\.venv\Scripts\python.exe -
```

Confirm the live server OpenAPI includes report generation:

```powershell
@'
import json
from urllib.request import urlopen
target = "/audit-review-jobs/{job_id}/generate-report"
with urlopen("http://127.0.0.1:8000/openapi.json", timeout=10) as response:
    paths = json.load(response)["paths"]
print(target in paths)
print(paths.get(target, {}).keys())
'@ | .\.venv\Scripts\python.exe -
```
