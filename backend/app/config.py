"""Application settings, loaded from environment variables and validated at startup.

Core settings are required. Provider settings stay optional until the phase that uses them;
`provider_configuration()` reports which providers are set up.
"""

from enum import StrEnum
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

WEAK_SECRET_MARKERS = ("change-me", "changeme", "secret", "password", "example")


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class ConfigError(RuntimeError):
    """Raised when required settings are missing or invalid. Never contains secret values."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # Core (required)
    app_env: AppEnv
    app_secret_key: SecretStr
    database_url: SecretStr
    redis_url: SecretStr

    # Core (optional)
    app_version: str = "0.0.0"
    log_level: str = "INFO"
    app_timezone: str = "Asia/Kolkata"
    frontend_origin: str = "http://localhost:3000"
    frontend_url: str = "http://localhost:3000"
    public_backend_url: str | None = None

    # OpenAI (Phase 2)
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    # Only sent for reasoning models (e.g. "none", "minimal", "low"); lower effort = lower latency.
    openai_reasoning_effort: str | None = None
    openai_timeout_s: float = Field(default=8.0, gt=0, le=60)

    # Deepgram (TTS from Phase 3, STT from Phase 4). STT defaults: docs/benchmarks/stt.md
    deepgram_api_key: SecretStr | None = None
    deepgram_stt_model: str = "nova-3"
    deepgram_stt_language: str = "en-IN"
    # Silence (ms) after which Deepgram marks the end of speech (speech_final)
    deepgram_stt_endpointing_ms: int = Field(default=300, ge=10, le=5000)
    # Backstop: gap between words (ms) that ends an utterance even without speech_final
    deepgram_stt_utterance_end_ms: int = Field(default=1000, ge=1000, le=5000)
    # Digits/currency formatting. Off: it holds back answers that end in a number (4 s+)
    deepgram_stt_smart_format: bool = False
    # Comma-separated words to boost on every call; job-specific ones are added per call
    deepgram_stt_keyterms: str = "CTC,LPA,lakhs,notice period"

    # Exotel (Phase 5): names to be re-checked against Exotel docs
    exotel_api_key: SecretStr | None = None
    exotel_api_token: SecretStr | None = None
    exotel_account_sid: str | None = None
    exotel_subdomain: str | None = None
    exotel_caller_id: str | None = None

    # Kitten TTS (Phase 3). Empty values use the model baked into the image and the voice the
    # user chose in the Phase 3 listening test.
    kitten_model_path: str | None = None
    kitten_voice: str | None = None
    tts_threads: int = Field(default=2, ge=1, le=16)  # ONNX Runtime threads per synthesis
    tts_timeout_s: float = Field(default=3.0, gt=0, le=30)
    # Load the voice model at startup. Tests turn this off; nothing can speak without it.
    tts_preload: bool = True
    # Which TTS speaks: "auto" = Deepgram Aura when DEEPGRAM_API_KEY is set, else Kitten.
    tts_provider: Literal["auto", "deepgram", "kitten"] = "auto"
    # With Deepgram as primary, keep Kitten loaded and use it when Deepgram fails.
    tts_fallback: bool = True
    deepgram_tts_voice: str | None = None  # e.g. aura-2-asteria-en; empty = aura-2-harmonia-en
    deepgram_tts_gain_db: float = Field(default=6.0, ge=-12, le=12)  # loudness match with Kitten
    deepgram_tts_first_byte_timeout_s: float = Field(default=1.5, gt=0, le=10)
    # Disk cache for fixed phrases from paid providers (survives restarts)
    tts_cache_dir: str = "artifacts/tts-cache"

    # Google Sheets (Phase 7)
    google_service_account_json: str | None = None
    google_sheet_id: str | None = None

    # Calling
    max_concurrent_calls: int = Field(default=1, ge=1, le=2)
    max_call_attempts: int = Field(default=3, ge=1, le=10)
    retry_interval_days: int = Field(default=2, ge=2, le=4)

    @field_validator("*", mode="before")
    @classmethod
    def _empty_string_is_unset(cls, value: Any) -> Any:
        # `.env.example` ships keys with empty values; treat them as not set.
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("app_secret_key")
    @classmethod
    def _secret_long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("must be at least 32 characters")
        return value

    @field_validator("database_url")
    @classmethod
    def _async_postgres(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("must start with postgresql+asyncpg://")
        return value

    @field_validator("redis_url")
    @classmethod
    def _redis_scheme(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith(("redis://", "rediss://")):
            raise ValueError("must start with redis:// or rediss://")
        return value

    @model_validator(mode="after")
    def _production_rules(self) -> "Settings":
        if self.app_env is not AppEnv.PRODUCTION:
            return self
        secret = self.app_secret_key.get_secret_value().lower()
        if any(marker in secret for marker in WEAK_SECRET_MARKERS):
            raise ValueError("APP_SECRET_KEY looks like a placeholder; generate a random value")
        if not (self.public_backend_url or "").startswith("https://"):
            raise ValueError("PUBLIC_BACKEND_URL must be an https:// URL in production")
        return self

    def provider_configuration(self) -> dict[str, bool]:
        """Which external providers have their settings filled in (not whether they work)."""
        return {
            "openai": bool(self.openai_api_key and self.openai_model),
            "deepgram": bool(self.deepgram_api_key),
            "exotel": bool(
                self.exotel_api_key
                and self.exotel_api_token
                and self.exotel_account_sid
                and self.exotel_subdomain
                and self.exotel_caller_id
            ),
            "kitten_tts": True,  # local model with defaults; whether it loaded is in TTS status
            "google_sheets": bool(self.google_service_account_json and self.google_sheet_id),
        }


def load_settings(**overrides: Any) -> Settings:
    """Build settings, turning validation errors into a readable message of variable names only."""
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            name = ".".join(str(part) for part in error["loc"]).upper() or "SETTINGS"
            unset = error["type"] == "missing" or error.get("input") is None
            reason = "is required" if unset else error["msg"]
            problems.append(f"  - {name}: {reason}")
        raise ConfigError(
            "Invalid configuration. Fix these environment variables:\n" + "\n".join(problems)
        ) from None


@lru_cache
def get_settings() -> Settings:
    return load_settings()
