# Configuration
# Conforme SP-BE-01

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "PP1 Backend"
    app_version: str = "0.1.0"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False

    # API
    api_version: str = "v1"
    api_prefix: str = "/v1"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Database — must be set via DATABASE_URL env var
    database_url: str = "postgresql://localhost:5432/pp1"

    # Logging
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    # Nikufra data directory (ISOP XLSX + PP PDFs)
    nikufra_data_dir: str = "data/nikufra"

    # Security
    expose_stack_traces: bool = False  # Nunca expor em produção
    api_keys: list[str] = []  # Empty = dev mode (skip auth)

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:5174"]

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore",
    }


settings = Settings()
