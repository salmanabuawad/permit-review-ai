"""Runtime configuration.

All values can be overridden with environment variables prefixed BBP_.
Production (Ubuntu) uses PostgreSQL+PostGIS; the local POC defaults to SQLite so
it runs without any server install. Nothing here enables an external integration:
every connector is disabled by default for the pilot (tender scope: offline only).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # repo root
BACKEND = ROOT / "backend"
KNOWLEDGE = ROOT / "knowledge"


def _env(name: str, default: str) -> str:
    return os.environ.get(f"BBP_{name}", default)


def _first_font(*paths: str) -> str:
    """The first font file that exists (Windows dev box, Ubuntu server, this Linux PC); else the first path."""
    return next((p for p in paths if Path(p).exists()), paths[0])


@dataclass(frozen=True)
class Settings:
    database_url: str = _env("DATABASE_URL", f"sqlite:///{(ROOT / 'var' / 'bbp.sqlite3').as_posix()}")
    storage_dir: Path = Path(_env("STORAGE_DIR", str(ROOT / "var" / "storage")))
    knowledge_dir: Path = Path(_env("KNOWLEDGE_DIR", str(KNOWLEDGE)))
    environment: str = _env("ENV", "dev")                     # dev | test | production
    # Hebrew-capable TTF used for PDF reports. On Ubuntu: /usr/share/fonts/truetype/noto/NotoSansHebrew-Regular.ttf
    pdf_font: str = _env("PDF_FONT", _first_font(
        r"C:\Windows\Fonts\arial.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    pdf_font_bold: str = _env("PDF_FONT_BOLD", _first_font(
        r"C:\Windows\Fonts\arialbd.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
    # Optional DWG -> DXF converter (ODA File Converter). Without it DWG files are
    # stored and flagged NEEDS_CONVERSION; they are never "measured" from an image.
    oda_converter: str = _env("ODA_CONVERTER", "")
    # The language model, OpenAI-compatible (/v1/chat/completions). Default: local Ollama's /v1. With the model on
    # a separate AI PC (as muniflow.kortexd.com does), point it at the LLM relay: http://127.0.0.1:18112/v1.
    llm_base_url: str = _env("LLM_BASE_URL", _env("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/v1")
    llm_timeout_s: float = float(_env("LLM_TIMEOUT", "180"))
    # LLM relay (app/ai/relay.py, its own process): the AI PC's agent pulls model calls from it over HTTPS.
    llm_relay_token: str = _env("LLM_RELAY_TOKEN", "")
    vision_model: str = _env("VISION_MODEL", "ministral-3-8b-vision")
    typing_worker: bool = _env("TYPING_WORKER", "false").lower() in ("1", "true", "yes")   # on in the deployed app
    onboarding_worker: bool = _env("ONBOARDING_WORKER", "false").lower() in ("1", "true", "yes")  # authority discovery jobs
    # the app never fetches regulatory sites itself: crawls are queued for the crawler process (app.crawler_worker),
    # which runs as its own OS user behind a public-internet-only firewall
    crawler_separate: bool = _env("CRAWLER_SEPARATE", "false").lower() in ("1", "true", "yes")
    login_required: bool = _env("LOGIN_REQUIRED", "false").lower() in ("1", "true", "yes")  # app login page + session cookie
    login_user_id: str = _env("LOGIN_USER_ID", "u-ha-admin")   # the single administrator the login maps to
    llm_relay_poll_interval_s: float = float(_env("LLM_RELAY_POLL_INTERVAL", "1"))
    llm_relay_pickup_timeout_s: float = float(_env("LLM_RELAY_PICKUP_TIMEOUT", "15"))
    llm_relay_response_timeout_s: float = float(_env("LLM_RELAY_RESPONSE_TIMEOUT", "300"))
    max_upload_mb: int = int(_env("MAX_UPLOAD_MB", "200"))
    # Request packages: files downloaded from the links inside an uploaded request form (intake/attachments.py)
    follow_request_links: bool = _env("FOLLOW_REQUEST_LINKS", "true").lower() not in ("0", "false", "no")
    max_package_mb: int = int(_env("MAX_PACKAGE_MB", "500"))
    # Pilot hard rule: no live external integrations.
    integrations_enabled: bool = _env("INTEGRATIONS_ENABLED", "false").lower() == "true"
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        _env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")))


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
