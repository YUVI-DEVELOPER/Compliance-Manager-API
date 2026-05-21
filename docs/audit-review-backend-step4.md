# Audit Review Backend Step 4

Step 4 integrates the existing standalone Veeva MCP server with the Compliance Manager FastAPI backend.

## Environment

Add this backend environment variable:

```env
VEEVA_MCP_BASE_URL=http://127.0.0.1:8010
VEEVA_AUDIT_EXTRACTION_CHUNK_DAYS=14
VEEVA_AUDIT_LOOKBACK_DAYS=30
```

The Compliance Manager backend does not store Veeva Vault credentials. Vault DNS, username, password, client ID, and session handling remain in the sibling `veeva_mcp_server`.
Large audit-review windows are split into `VEEVA_AUDIT_EXTRACTION_CHUNK_DAYS` sized MCP requests per selected audit trail type before analysis.
Requests older than `VEEVA_AUDIT_LOOKBACK_DAYS` fail fast with a clear extraction error so review periods are not silently clamped.

## Endpoints

Create an audit review job for an asset:

```http
POST /asset/{asset_id}/audit-review-jobs
```

List audit review jobs for an asset:

```http
GET /asset/{asset_id}/audit-review-jobs
```

Get audit review job details:

```http
GET /audit-review-jobs/{job_id}
```

Extract audit trail records through the MCP server:

```http
POST /audit-review-jobs/{job_id}/extract
```

List stored normalized records:

```http
GET /audit-review-jobs/{job_id}/records?include_raw=false
```

`include_raw` defaults to `false` so raw Veeva payloads are not returned during normal debugging.

## Postman Examples

Create a job:

```json
{
  "review_start_dt": "2026-04-01T00:00:00Z",
  "review_end_dt": "2026-04-25T00:00:00Z",
  "audit_trail_type": "login_audit_trail",
  "veeva_instance_name": "Veeva Quality Vault",
  "veeva_app_name": "QualityDocs",
  "vault_dns": "masked-or-display-only",
  "requested_by": "user@example.com"
}
```

Extract records:

```http
POST {{base_url}}/audit-review-jobs/{{job_id}}/extract
```

Fetch records without raw payload:

```http
GET {{base_url}}/audit-review-jobs/{{job_id}}/records
```

Fetch records with raw payload only when needed:

```http
GET {{base_url}}/audit-review-jobs/{{job_id}}/records?include_raw=true
```

## Intentional Exclusions

This step does not implement:

- scheduler
- PDF export
- AI report generation
- approval workflow
- deterministic checks
- scoring logic
- frontend changes
- direct Veeva Vault authentication from `v_API`

## Next Step

The next backend step will add deterministic checks and scoring using the stored normalized `audit_trail_record` rows.
