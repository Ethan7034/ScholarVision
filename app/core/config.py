from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve this file's absolute path, then walk up three levels:
# app/core/config.py -> app/ -> ScholarVision/ (project root).
current_file = Path(__file__).resolve()
BASE_DIR = current_file.parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    # Load .env by absolute path so the process cwd never matters.
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    PROJECT_NAME: str = "Scholar Vision"
    INTERN_API_KEY: str = ""

    # ------------------------------------------------------------------
    # Security & session (Layer 2)
    # Real values belong in .env (gitignored); source keeps only insecure
    # development defaults.
    # ------------------------------------------------------------------
    SECRET_KEY: str = "dev-only-insecure-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # Session cookie name and attributes (server-side session + 302 redirect).
    SESSION_COOKIE_NAME: str = "sv_session"
    COOKIE_SECURE: bool = False      # 经 Cloudflare Tunnel 走 HTTPS 时设 True
    COOKIE_SAMESITE: str = "lax"

    # ------------------------------------------------------------------
    # Data layer (Layer 7)
    # Defaults to a local SQLite file; move to PostgreSQL by changing
    # DATABASE_URL in .env, no code change required.
    # ------------------------------------------------------------------
    DATABASE_URL: str = "sqlite:///./scholar_vision.db"

    # ------------------------------------------------------------------
    # Redis: cache + job state (Layer 7)
    # store.py probes once per process and degrades to in-process memory
    # when unreachable, so the project runs without a local Redis install.
    # ------------------------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_TTL_ANALYZE: int = 24 * 3600   # per-file analysis result, 24h
    CACHE_TTL_SEARCH: int = 10 * 60      # arXiv search results, 10min

    # Charts analyzed concurrently per job against the VLM API.
    MAX_CONCURRENT_ANALYSIS: int = 3

    # ------------------------------------------------------------------
    # Standalone worker (v2.1): Redis-backed queue when Redis is reachable,
    # in-process execution otherwise.
    # ------------------------------------------------------------------
    QUEUE_NAME: str = "sv:queue:analyze"
    PROCESSING_LIST: str = "sv:queue:processing"
    WORKER_CONCURRENCY: int = 2          # PDF jobs one worker handles at once


settings = Settings()
