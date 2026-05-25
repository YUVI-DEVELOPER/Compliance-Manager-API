import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url


load_dotenv()
BASE_DIR = Path(__file__).resolve().parents[2]


def _env_bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    raw_value = os.getenv(key, str(default)).strip()
    try:
        return int(raw_value)
    except ValueError:
        raise ValueError(f"{key} must be an integer") from None


def _first_csv_value(value: str | None) -> str:
    if not value:
        return ""
    return value.split(",")[0].strip()


def _env_csv(key: str, default: str = "") -> tuple[str, ...]:
    raw_value = os.getenv(key, default)
    return tuple(item.strip().rstrip("/") for item in raw_value.split(",") if item.strip())


_DEFAULT_DEV_CORS_ORIGIN_REGEX = (
    r"^http://("
    r"localhost|127\.0\.0\.1|"
    r"10(?:\.\d{1,3}){3}|"
    r"192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}"
    r"):\d{4,5}$"
)


class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "ValidateNow")
    APP_ENV: str = os.getenv("APP_ENV", "development")
    APP_DEBUG: bool = os.getenv("APP_DEBUG", "true").lower() == "true"
    API_HOST: str = os.getenv("API_HOST", "127.0.0.1")
    API_PORT: int = _env_int("API_PORT", 8005)
    FRONTEND_PORT: int = _env_int("FRONTEND_PORT", 5175)
    CORS_ORIGINS: tuple[str, ...] = _env_csv(
        "CORS_ORIGINS",
        f"http://localhost:{FRONTEND_PORT},http://127.0.0.1:{FRONTEND_PORT}",
    )
    CORS_ALLOW_ORIGIN_REGEX: str | None = (
        os.getenv("CORS_ALLOW_ORIGIN_REGEX", _DEFAULT_DEV_CORS_ORIGIN_REGEX if APP_ENV != "production" else "").strip()
        or None
    )
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:root@localhost:5432/ValidateNow",
    )
    RUN_MIGRATIONS_ON_STARTUP: bool = os.getenv("RUN_MIGRATIONS_ON_STARTUP", "true").lower() == "true"
    AUDIT_REVIEW_SCHEDULER_ENABLED: bool = _env_bool("AUDIT_REVIEW_SCHEDULER_ENABLED", "true")
    AUDIT_REVIEW_SCHEDULER_INTERVAL_SECONDS: int = _env_int("AUDIT_REVIEW_SCHEDULER_INTERVAL_SECONDS", 60)
    AUDIT_REVIEW_SCHEDULER_INITIAL_DELAY_SECONDS: int = _env_int("AUDIT_REVIEW_SCHEDULER_INITIAL_DELAY_SECONDS", 10)
    LLM_ENABLED: bool = os.getenv("LLM_ENABLED", "false").lower() == "true"
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", os.getenv("AI_PROVIDER",   "openai-compatible"))
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", os.getenv("AI_BASE_URL", "https://api.openai.com/v1"))
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", os.getenv("AI_API_KEY", ""))
    LLM_MODEL: str = os.getenv("LLM_MODEL", os.getenv("AI_MODEL", ""))
    LLM_ORGANIZATION_ID: str | None = os.getenv("LLM_ORGANIZATION_ID", os.getenv("AI_ORGANIZATION_ID"))
    LLM_PROJECT_ID: str | None = os.getenv("LLM_PROJECT_ID", os.getenv("AI_PROJECT_ID"))
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", os.getenv("AI_TIMEOUT_SECONDS", "45")))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "1"))
    LLM_MAX_OUTPUT_TOKENS: int = _env_int("LLM_MAX_OUTPUT_TOKENS", 2048)
    URS_GENERATION_MAX_PROMPT_CHARS: int = _env_int("URS_GENERATION_MAX_PROMPT_CHARS", 12000)
    VEEVA_PUBLISH_ENABLED: bool = os.getenv("VEEVA_PUBLISH_ENABLED", "false").lower() == "true"
    VEEVA_BASE_URL: str = os.getenv("VEEVA_BASE_URL", "")
    VEEVA_PUBLISH_ENDPOINT: str = os.getenv("VEEVA_PUBLISH_ENDPOINT", "")
    VEEVA_AUTH_METHOD: str = os.getenv("VEEVA_AUTH_METHOD", "basic")
    VEEVA_USERNAME: str = os.getenv("VEEVA_USERNAME", "")
    VEEVA_PASSWORD: str = os.getenv("VEEVA_PASSWORD", "")
    VEEVA_API_TOKEN: str = os.getenv("VEEVA_API_TOKEN", "")
    VEEVA_TIMEOUT_SECONDS: float = float(os.getenv("VEEVA_TIMEOUT_SECONDS", "30"))
    VEEVA_VERIFY_SSL: bool = os.getenv("VEEVA_VERIFY_SSL", "true").lower() == "true"
    VEEVA_URS_DOCUMENT_TYPE: str = os.getenv("VEEVA_URS_DOCUMENT_TYPE", "URS")
    VEEVA_URS_DOCUMENT_CLASS: str = os.getenv("VEEVA_URS_DOCUMENT_CLASS", "User Requirements Specification")
    VEEVA_MCP_BASE_URL: str = os.getenv("VEEVA_MCP_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
    VEEVA_AUDIT_EXTRACTION_CHUNK_DAYS: int = _env_int("VEEVA_AUDIT_EXTRACTION_CHUNK_DAYS", 14)
    VEEVA_AUDIT_LOOKBACK_DAYS: int = _env_int("VEEVA_AUDIT_LOOKBACK_DAYS", 30)
    FILE_UPLOAD_DIR: str = os.getenv("FILE_UPLOAD_DIR", str(BASE_DIR / "uploads"))
    FILE_STORAGE_DIR: str = os.getenv("FILE_STORAGE_DIR", str(BASE_DIR / "filestorage"))
    MAX_FILE_UPLOAD_MB: int = int(os.getenv("MAX_FILE_UPLOAD_MB", "25"))
    DOCUMENT_VECTORIZATION_ENABLED: bool = _env_bool("DOCUMENT_VECTORIZATION_ENABLED", "true")
    DOCUMENT_VECTORIZATION_RESUME_ON_STARTUP: bool = _env_bool("DOCUMENT_VECTORIZATION_RESUME_ON_STARTUP", "true")
    DOCUMENT_VECTORIZATION_STARTUP_BATCH_SIZE: int = int(os.getenv("DOCUMENT_VECTORIZATION_STARTUP_BATCH_SIZE", "25"))
    WEAVIATE_URL: str = os.getenv("WEAVIATE_URL", "http://localhost:8086")
    WEAVIATE_GRPC_PORT: int = int(os.getenv("WEAVIATE_GRPC_PORT", "50051"))
    WEAVIATE_API_KEY: str = os.getenv(
        "WEAVIATE_API_KEY",
        _first_csv_value(os.getenv("WEAVIATE_AUTH_APIKEY_ALLOWED_KEYS")) or "weaviate_secret_key",
    )
    WEAVIATE_COLLECTION: str = os.getenv("WEAVIATE_COLLECTION", "ValidateNowDocumentChunk")
    VECTOR_EMBEDDING_MODEL: str = os.getenv("VECTOR_EMBEDDING_MODEL", os.getenv("MODEL_NAME", "BAAI/bge-base-en"))
    VECTOR_EMBEDDING_MODEL_DIR: str = os.getenv("VECTOR_EMBEDDING_MODEL_DIR", os.getenv("MODEL_DIR", ""))
    VECTOR_CHUNK_SIZE: int = int(os.getenv("VECTOR_CHUNK_SIZE", os.getenv("CHUNK_SIZE", "512")))
    VECTOR_CHUNK_OVERLAP_SENTENCES: int = int(
        os.getenv("VECTOR_CHUNK_OVERLAP_SENTENCES", os.getenv("CHUNK_OVERLAP_SENTENCES", "1"))
    )
    VECTOR_MIN_CONTENT_WORDS: int = int(os.getenv("VECTOR_MIN_CONTENT_WORDS", os.getenv("MIN_CONTENT_WORDS", "60")))
    VECTOR_TENANT_ID: str = os.getenv("VECTOR_TENANT_ID", os.getenv("DEFAULT_TENANT_ID", ""))
    DOCUMENT_AI_AUTOFILL_ENABLED: bool = _env_bool("DOCUMENT_AI_AUTOFILL_ENABLED", "true")
    DOCUMENT_AI_AUTOFILL_USE_OCR: bool = _env_bool("DOCUMENT_AI_AUTOFILL_USE_OCR", "true")
    DOCUMENT_AI_USE_EMBEDDINGS: bool = _env_bool("DOCUMENT_AI_USE_EMBEDDINGS", "false")
    DOCUMENT_AI_USE_LLM_FALLBACK: bool = _env_bool("DOCUMENT_AI_USE_LLM_FALLBACK", "true")
    DOCUMENT_AI_CLASSIFIER_MODEL: str = os.getenv("DOCUMENT_AI_CLASSIFIER_MODEL", VECTOR_EMBEDDING_MODEL)
    DOCUMENT_AI_CONFIDENCE_THRESHOLD: float = float(os.getenv("DOCUMENT_AI_CONFIDENCE_THRESHOLD", "0.68"))
    DOCUMENT_AI_MAX_TEXT_CHARS: int = int(os.getenv("DOCUMENT_AI_MAX_TEXT_CHARS", "20000"))
    DOCUMENT_AI_OCR_MAX_PAGES: int = int(os.getenv("DOCUMENT_AI_OCR_MAX_PAGES", "3"))
    STEP2_AI_ASSISTANT_ENABLED: bool = _env_bool("STEP2_AI_ASSISTANT_ENABLED", "false")
    STEP2_AI_PROVIDER: str = os.getenv("STEP2_AI_PROVIDER", "openai_compatible")
    STEP2_AI_MODEL: str = os.getenv("STEP2_AI_MODEL", "")
    STEP2_AI_API_KEY: str = os.getenv("STEP2_AI_API_KEY", "")
    STEP2_AI_BASE_URL: str = os.getenv("STEP2_AI_BASE_URL", "https://api.openai.com/v1")
    STEP2_AI_TEMPERATURE: float = float(os.getenv("STEP2_AI_TEMPERATURE", "0.1"))
    STEP2_AI_MAX_TOKENS: int = _env_int("STEP2_AI_MAX_TOKENS", 3000)
    STEP2_AI_TIMEOUT_SECONDS: float = float(os.getenv("STEP2_AI_TIMEOUT_SECONDS", "60"))
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = _env_int("ACCESS_TOKEN_EXPIRE_MINUTES", 480)
    DEFAULT_ADMIN_EMAIL: str = os.getenv("DEFAULT_ADMIN_EMAIL", "")
    DEFAULT_ADMIN_PASSWORD: str = os.getenv("DEFAULT_ADMIN_PASSWORD", "")
    DEFAULT_ADMIN_NAME: str = os.getenv("DEFAULT_ADMIN_NAME", "System Admin")
    PASSWORD_HASH_SCHEME: str = os.getenv("PASSWORD_HASH_SCHEME", "bcrypt")

    @property
    def sqlalchemy_database_url(self) -> URL:
        return make_url(self.DATABASE_URL)

    @property
    def database_name(self) -> str:
        database = self.sqlalchemy_database_url.database
        if not database:
            raise ValueError("DATABASE_URL must include a database name")
        return database

    def render_database_url(self, database: str | None = None, drivername: str | None = None) -> str:
        url = self.sqlalchemy_database_url
        if database is not None:
            url = url.set(database=database)
        if drivername is not None:
            url = url.set(drivername=drivername)
        return url.render_as_string(hide_password=False)

    @property
    def admin_database_url(self) -> str:
        return self.render_database_url(database="postgres")

    @property
    def asyncpg_admin_database_url(self) -> str:
        return self.render_database_url(database="postgres", drivername="postgresql")


@lru_cache
def get_settings() -> Settings:
    return Settings()
