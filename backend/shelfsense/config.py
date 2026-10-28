"""Runtime configuration (12-factor: everything comes from the environment)."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- general ---------------------------------------------------------
    app_env: str = "local"  # local | staging | production
    log_level: str = "INFO"
    demo_mode: bool = True  # exposes /api/demo/* helpers; set false in production
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    static_dir: str = "../frontend/dist"
    ops_api_key: str | None = None  # when set, owner/ops endpoints require X-API-Key
    chat_rate_limit_per_min: int = 30

    # --- Google AI -------------------------------------------------------
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    google_genai_use_vertexai: bool = False  # true => Vertex AI via ADC (recommended on Cloud Run)
    google_api_key: str | None = None  # Gemini API key alternative for local dev
    gemini_model: str = "gemini-2.5-flash"
    llm_mode: str = "auto"  # auto | on | off  (auto => on when credentials are configured)
    llm_timeout_s: float = 30.0
    session_db_url: str | None = None  # e.g. postgresql+asyncpg://...  (default: in-memory sessions)

    # --- data layer ------------------------------------------------------
    store_backend: str = "memory"  # memory | firestore
    firestore_database: str = "(default)"
    bigquery_dataset: str | None = None  # when set, demand events are streamed to BigQuery
    sales_backend: str = "memory"  # memory (synthetic demo history) | bigquery (<dataset>.sales_daily)
    seed_on_start: bool = True

    # --- inventory policy ------------------------------------------------
    service_level_z: float = 1.65  # ~95% cycle service level
    review_period_days: int = 7
    capture_rate: float = Field(0.5, ge=0, le=1)  # share of unmet shoppers we expect to convert
    assistant_reach: float = Field(
        0.3, gt=0, le=1
    )  # share of all shoppers the assistant sees (scales observed demand)

    # --- search thresholds -------------------------------------------------
    full_match_coverage: float = 0.75
    partial_match_coverage: float = 0.34

    # --- notifications ---------------------------------------------------
    notify_webhook_url: str | None = (
        None  # optional: POST each notification (WhatsApp/SMS bridge, Zapier, ...)
    )

    @property
    def llm_enabled(self) -> bool:
        if self.llm_mode == "off":
            return False
        if self.llm_mode == "on":
            return True
        return bool(self.google_api_key) or self.google_genai_use_vertexai

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def export_genai_env(s: Settings) -> None:
    """google-genai / ADK read credentials from os.environ, so mirror our settings there."""
    if s.google_genai_use_vertexai:
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"
    if s.google_api_key:
        os.environ["GOOGLE_API_KEY"] = s.google_api_key
    if s.google_cloud_project:
        os.environ["GOOGLE_CLOUD_PROJECT"] = s.google_cloud_project
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", s.google_cloud_location)
