# Compliance Manager Backend Schema Management

## Fresh setup

For a new local PostgreSQL instance, you can optionally create the database itself with:

```bash
python -m app.core.dev_database
```

That helper is development-only. It creates the target database if it does not already exist, but it does not run in production.

After the database exists, starting the FastAPI app will automatically run `alembic upgrade head` before serving requests. On a fresh environment, that creates the full versioned schema, PostgreSQL functions, triggers, indexes, and lookup seed data.

## Existing database upgrades

If the database already exists, startup runs the same Alembic upgrade flow and only applies pending revisions. If the schema is already current, nothing is recreated and startup remains a no-op from a schema perspective.

You can also run the migration bootstrap directly during deployment:

```bash
python -m app.core.db_migrations
```

## Running the API locally

The local API port is configured with `API_PORT` in `.env`. The default is `8005`.

```bash
python -m app.main
```

If you start with Uvicorn directly, pass the same port explicitly:

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8005
```

The frontend dev port used for default CORS origins is configured with `FRONTEND_PORT`. The default is `5175`.

## Future schema changes

The Python codebase is now the source of truth:

1. Update SQLAlchemy models for ordinary schema changes such as columns, defaults, indexes, and constraints.
2. Generate a migration with Alembic autogenerate:

```bash
alembic revision --autogenerate -m "describe_change"
```

3. Review the generated migration and add any PostgreSQL-specific objects manually with `op.execute(...)`, such as trigger functions, triggers, or seed-data updates.
4. Apply the migration with:

```bash
alembic upgrade head
```

## AI-assisted URS draft configuration

Step 3 adds optional AI-assisted URS generation on top of the authored-document foundation. The backend reads these environment variables when AI-assisted draft generation is enabled:

- `AI_PROVIDER`: set to `openai` to enable provider calls, or leave as `disabled` to keep AI generation off.
- `AI_BASE_URL`: base URL for the provider REST API. Defaults to `https://api.openai.com/v1`.
- `AI_API_KEY`: server-side API key used for provider authentication.
- `AI_MODEL`: model name to use for URS generation.
- `AI_ORGANIZATION_ID` and `AI_PROJECT_ID`: optional OpenAI scoping headers.
- `AI_TIMEOUT_SECONDS`: request timeout for generation calls.

If AI is disabled or unavailable, the dedicated `create-ai-draft` flow safely falls back to template-prefill generation and records that fallback in document traceability metadata. Regeneration of an existing draft returns a clear error instead of overwriting the current draft with fallback content.

## Veeva publish configuration

Step 4 adds outbound publishing of approved URS documents to Veeva. Publishing is only attempted when `VEEVA_PUBLISH_ENABLED=true`, and the backend will return a clear configuration error instead of faking success when the integration is not fully wired.

- `VEEVA_PUBLISH_ENABLED`: enables the outbound publish workflow.
- `VEEVA_BASE_URL`: Veeva service base URL.
- `VEEVA_PUBLISH_ENDPOINT`: relative endpoint used for the publish call.
- `VEEVA_AUTH_METHOD`: `basic`, `bearer`, `token`, or `none`.
- `VEEVA_USERNAME` and `VEEVA_PASSWORD`: credentials for basic authentication.
- `VEEVA_API_TOKEN`: bearer token when token auth is used.
- `VEEVA_TIMEOUT_SECONDS`: outbound request timeout.
- `VEEVA_VERIFY_SSL`: toggles TLS certificate verification.
- `VEEVA_URS_DOCUMENT_TYPE` and `VEEVA_URS_DOCUMENT_CLASS`: optional mapping values included in the outbound payload for URS publishes.

Successful publishes update authored-document publish status and store the returned Veeva reference metadata. When the response includes enough metadata to support the existing linked-document module, the system also creates or updates a `VEEVA_VAULT` linked-document reference for the same asset or release target.

## Document vectorization configuration

Document Linking uploads now store local linked-document files under `filestorage/documents/...`, create PostgreSQL vectorization tracking rows, and queue background vectorization for `.pdf`, `.docx`, and `.txt` files. Unsupported formats still link normally and receive `NOT_SUPPORTED_FOR_VECTORIZATION`.

- `FILE_STORAGE_DIR`: local durable file storage root. Defaults to `v_API/filestorage`.
- `DOCUMENT_VECTORIZATION_ENABLED`: set `false` to skip background vectorization. Defaults to `true`.
- `DOCUMENT_VECTORIZATION_RESUME_ON_STARTUP`: resumes active `QUEUED` vectorization jobs after backend restarts. Defaults to `true`.
- `DOCUMENT_VECTORIZATION_STARTUP_BATCH_SIZE`: maximum queued jobs resumed on startup. Defaults to `25`.
- `WEAVIATE_URL`: Weaviate HTTP URL. Defaults to `http://localhost:8086`.
- `WEAVIATE_GRPC_PORT`: Weaviate gRPC port. Defaults to `50051`.
- `WEAVIATE_API_KEY`: API key for Weaviate. Defaults to `weaviate_secret_key` for local compose.
- `WEAVIATE_COLLECTION`: target collection for document chunks. Defaults to `ValidateNowDocumentChunk`.
- `VECTOR_EMBEDDING_MODEL`: sentence-transformers model. Defaults to `BAAI/bge-base-en`.
- `VECTOR_EMBEDDING_MODEL_DIR`: optional local model path when running without model downloads.
- `VECTOR_CHUNK_SIZE`, `VECTOR_CHUNK_OVERLAP_SENTENCES`, `VECTOR_MIN_CONTENT_WORDS`: chunking controls adapted from the RAG Builder processor.
- `VECTOR_TENANT_ID`: optional tenant metadata copied into each Weaviate chunk.

Local Weaviate can be started with:

```bash
docker compose -f docker-compose.weaviate.yml up -d
```

Then install backend dependencies and start the app as usual. Startup migrations create `document_vectorization_job`; the upload request returns immediately after queueing, while the FastAPI background task writes chunks and vectors to Weaviate.

## Document Linking AI Autofill

Document Linking can analyze staged uploads before the final document-link save. The pipeline uses native text extraction first, OCR only as a best-effort fallback for scanned PDFs, regex/rule extraction for document ID and version, and rule/semantic classification for document type. LLM fallback is only used when deterministic confidence is low and the existing LLM configuration is enabled.

- `DOCUMENT_AI_AUTOFILL_ENABLED`: enables the analysis endpoint. Defaults to `true`.
- `DOCUMENT_AI_AUTOFILL_USE_OCR`: allows OCR fallback for scanned PDFs when optional OCR dependencies are available. Defaults to `true`.
- `DOCUMENT_AI_USE_EMBEDDINGS`: enables sentence-transformer similarity for document type classification. Defaults to `false`.
- `DOCUMENT_AI_USE_LLM_FALLBACK`: allows the configured OpenAI-compatible LLM fallback for ambiguous results. Defaults to `true`.
- `DOCUMENT_AI_CONFIDENCE_THRESHOLD`: confidence below which fallback/review warnings apply. Defaults to `0.68`.
- `DOCUMENT_AI_CLASSIFIER_MODEL`: embedding model used when embedding classification is enabled. Defaults to `BAAI/bge-base-en`.

## Dev database creation vs production migration

- `python -m app.core.dev_database` is only for local development convenience when the PostgreSQL database itself does not exist yet.
- Production should assume the database already exists and should only run versioned Alembic migrations.
- Normal schema evolution should happen through model changes plus Alembic revisions, not ad hoc SQL in pgAdmin or `psql`.

## Albemic confic 
- `
[alembic:exclude]
validate_now = validate_now:*
main = main:*
access = access:*
forceUpdate = forceUpdate:*

[alembic:include_object]

Include the validate steps and the configuration settings through the valide endpoints 
