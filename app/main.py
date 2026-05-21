import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import engine
from app.core.db_migrations import upgrade_to_head_async
from app.core.logging_config import configure_app_logging
from app.routers.api_router import api_router
from app.services.audit_review_scheduler_service import process_due_audit_review_schedules_background
from app.services.document_vectorization_service import process_queued_document_vectorizations_background
from app.services.rbac_seed_service import seed_rbac_defaults

settings = get_settings()
configure_app_logging()
logger = logging.getLogger("app.api")


def _get_request_target(request: Request) -> str:
    request_target = request.url.path
    if request.url.query:
        request_target = f"{request_target}?{request.url.query}"
    return request_target


def _get_request_context(request: Request) -> tuple[str, str, str]:
    client_host = request.client.host if request.client is not None else "unknown"
    route = request.scope.get("route")
    endpoint = request.scope.get("endpoint")
    route_path = getattr(route, "path", "-")
    handler_name = getattr(endpoint, "__name__", "-")
    return client_host, route_path, handler_name


def _get_status_log_level(status_code: int) -> int:
    if status_code >= 500:
        return logging.ERROR
    if status_code >= 400:
        return logging.WARNING
    return logging.INFO


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.RUN_MIGRATIONS_ON_STARTUP:
        await upgrade_to_head_async()
    await seed_rbac_defaults()
    vectorization_resume_task = None
    audit_review_scheduler_task = None
    if settings.DOCUMENT_VECTORIZATION_ENABLED and settings.DOCUMENT_VECTORIZATION_RESUME_ON_STARTUP:
        vectorization_resume_task = asyncio.create_task(process_queued_document_vectorizations_background())
    if settings.AUDIT_REVIEW_SCHEDULER_ENABLED:
        audit_review_scheduler_task = asyncio.create_task(
            process_due_audit_review_schedules_background(
                poll_interval_seconds=settings.AUDIT_REVIEW_SCHEDULER_INTERVAL_SECONDS,
                initial_delay_seconds=settings.AUDIT_REVIEW_SCHEDULER_INITIAL_DELAY_SECONDS,
            )
        )
    try:
        yield
    finally:
        if vectorization_resume_task is not None and not vectorization_resume_task.done():
            vectorization_resume_task.cancel()
        if audit_review_scheduler_task is not None and not audit_review_scheduler_task.done():
            audit_review_scheduler_task.cancel()
        await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

upload_dir = Path(settings.FILE_UPLOAD_DIR)
upload_dir.mkdir(parents=True, exist_ok=True)

file_storage_dir = Path(settings.FILE_STORAGE_DIR)
file_storage_dir.mkdir(parents=True, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ALLOW_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_api_requests(request: Request, call_next):
    started_at = perf_counter()
    request_target = _get_request_target(request)

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (perf_counter() - started_at) * 1000
        client_host, route_path, handler_name = _get_request_context(request)
        logger.exception(
            "api_call_failed method=%s path=%s route=%s handler=%s client=%s duration_ms=%.2f",
            request.method,
            request_target,
            route_path,
            handler_name,
            client_host,
            duration_ms,
        )
        raise

    duration_ms = (perf_counter() - started_at) * 1000
    client_host, route_path, handler_name = _get_request_context(request)
    logger.log(
        _get_status_log_level(response.status_code),
        "api_call method=%s path=%s route=%s handler=%s status_code=%s duration_ms=%.2f client=%s",
        request.method,
        request_target,
        route_path,
        handler_name,
        response.status_code,
        duration_ms,
        client_host,
    )
    return response


app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.APP_ENV != "production",
    )
