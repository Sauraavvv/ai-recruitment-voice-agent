"""Application settings, loaded from environment variables and validated at startup.

Core settings are required. Provider settings stay optional until the phase that uses them;
`provider_configuration()` reports which providers are set up.
"""

import base64
import hashlib
import hmac
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

    @property
    def groq_keys(self) -> list[str]:
        """Every configured Groq key (GROQ_API_KEYS, then GROQ_API_KEY), without duplicates."""
        raw = []
        if self.groq_api_keys:
            raw += self.groq_api_keys.get_secret_value().replace("\n", ",").split(",")
        if self.groq_api_key:
            raw.append(self.groq_api_key.get_secret_value())
        keys: list[str] = []
        for key in (k.strip() for k in raw):
            if key and key not in keys:
                keys.append(key)
        return keys

    @property
    def signup_allowed(self) -> bool:
        if self.signup_enabled is not None:
            return self.signup_enabled
        return self.app_env is not AppEnv.PRODUCTION

    # Core (required)
    app_env: AppEnv
    app_secret_key: SecretStr
    database_url: SecretStr
    redis_url: SecretStr

    # Sign-up (POST /auth/signup) creates an organization and its super admin. Candidates, jobs,
    # calls and settings aren't separated per organization yet, so a new organization would see
    # the existing data: unset = allowed outside production only.
    signup_enabled: bool | None = None

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

    # Groq (telephonic round): writes interview questions from a requirement's JD. An
    # OpenAI-compatible API; the model is the open-weight gpt-oss-120b.
    groq_api_key: SecretStr | None = None
    # Several keys, comma-separated: requests rotate through them and move on to the next key
    # when one is rate limited or rejected. GROQ_API_KEY (one key) also works.
    groq_api_keys: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_reasoning_effort: str = "medium"  # low | medium | high
    groq_timeout_s: float = Field(default=60.0, gt=0, le=180)
    # Live telephonic round turns (phase-11 step 6b): low effort and a short budget. A turn that
    # takes longer gets a filler and the call moves on to the next question.
    groq_call_reasoning_effort: str = "low"
    groq_call_timeout_s: float = Field(default=5.0, gt=0, le=30)

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

    # Exotel (Phase 5). docs/telephony.md
    exotel_api_key: SecretStr | None = None
    exotel_api_token: SecretStr | None = None
    exotel_account_sid: str | None = None
    # API host for the account's region: api.exotel.com (Singapore) or api.in.exotel.com (Mumbai)
    exotel_subdomain: str | None = None
    exotel_caller_id: str | None = None  # the ExoPhone, as shown in the dashboard
    # The flow (app) with the Voicebot applet → Hangup; its id is in the dashboard's App Bazaar
    exotel_app_id: str | None = None
    exotel_connect_timeout_s: float = Field(default=5.0, gt=0, le=30)
    exotel_read_timeout_s: float = Field(default=10.0, gt=0, le=60)

    # Telephony media format on the stream (P5-T9: verified on a real call, docs/telephony.md).
    # Nothing else may hardcode the phone-side rate or frame size.
    telephony_encoding: Literal["slin", "mulaw"] = "slin"
    telephony_sample_rate: int = Field(default=8000)
    # Outgoing chunk size in bytes: a multiple of 320 (Exotel); 3200 = 200 ms at 8 kHz
    telephony_frame_bytes: int = Field(default=3200, ge=320, le=100_000)
    # How far ahead of real time outgoing audio may be sent (keeps `clear`/barge-in fast)
    telephony_send_ahead_ms: int = Field(default=200, ge=0, le=2000)
    # PoC capture of inbound audio + stream message log (testers' phones only; empty = off)
    telephony_capture_dir: str | None = "artifacts/calls"
    ring_timeout_s: int = Field(default=30, ge=10, le=120)
    max_call_duration_s: int = Field(default=900, ge=60, le=3600)
    # The telephonic round asks more open questions: a longer limit and wrap-up time
    telephonic_max_call_duration_s: int = Field(default=1200, ge=60, le=3600)
    telephonic_wrap_up_s: int = Field(default=1000, ge=60, le=3600)
    # Open questions need thinking time: wait longer before "are you still there?" (real
    # call 2026-11-22: 7 s re-asked a question while the candidate was still thinking)
    telephonic_silence_timeout_s: float = Field(default=12.0, ge=2, le=60)
    # Calling window in APP_TIMEZONE (phase-05 §6 decision: Mon-Sat 10:00-19:00)
    calling_days: str = "mon,tue,wed,thu,fri,sat"
    calling_hour_start: int = Field(default=10, ge=0, le=23)
    calling_hour_end: int = Field(default=19, ge=1, le=24)

    # Kitten TTS (Phase 3). Empty values use the model baked into the image and the voice the
    # user chose in the Phase 3 listening test.
    kitten_model_path: str | None = None
    kitten_voice: str | None = None
    tts_threads: int = Field(default=2, ge=1, le=16)  # ONNX Runtime threads per synthesis
    tts_timeout_s: float = Field(default=3.0, gt=0, le=30)
    # Load the voice model at startup. Tests turn this off; nothing can speak without it.
    tts_preload: bool = True
    # Which TTS speaks first. auto/kitten = Kitten (Iris, local), with Deepgram Aura as the
    # fallback when DEEPGRAM_API_KEY is set; deepgram = Deepgram first, Kitten as the fallback.
    # (Kitten chosen as primary 2026-11-19 after live calls.)
    tts_provider: Literal["auto", "deepgram", "kitten"] = "auto"
    # Keep the other voice loaded and use it when the first one fails.
    tts_fallback: bool = True
    deepgram_tts_voice: str | None = None  # e.g. aura-2-asteria-en; empty = aura-2-harmonia-en
    deepgram_tts_gain_db: float = Field(default=6.0, ge=-12, le=12)  # loudness match with Kitten
    deepgram_tts_first_byte_timeout_s: float = Field(default=1.5, gt=0, le=10)
    # Disk cache for fixed phrases from paid providers (survives restarts)
    tts_cache_dir: str = "artifacts/tts-cache"

    # Voice conversation (Phase 6, docs/voice-pipeline.md). Times in ms unless named _s.
    # VAD: webrtcvad aggressiveness 0-3, plus an energy gate (dBFS) under which a frame is never
    # speech. While the agent speaks the gate rises by VAD_ECHO_MARGIN_DB (echo of our own voice).
    vad_aggressiveness: int = Field(default=2, ge=0, le=3)
    vad_min_dbfs: float = Field(default=-45.0, ge=-90, le=0)
    vad_echo_margin_db: float = Field(default=6.0, ge=0, le=40)
    vad_speech_start_ms: int = Field(default=100, ge=20, le=1000)  # voiced run that starts speech
    vad_end_silence_ms: int = Field(default=400, ge=100, le=3000)  # silence → finalize() STT
    barge_in_min_ms: int = Field(default=300, ge=60, le=3000)  # speech before barge-in
    backchannel_max_ms: int = Field(default=600, ge=0, le=3000)  # "yes"/"okay" shorter than this
    greeting_wait_ms: int = Field(default=1200, ge=0, le=5000)  # wait for "Hello?" first
    silence_timeout_s: float = Field(default=7.0, ge=2, le=60)  # no speech after the agent
    max_utterance_s: float = Field(default=30.0, ge=5, le=120)
    call_wrap_up_s: int = Field(default=600, ge=60, le=3600)  # then read back and close
    stt_unavailable_s: float = Field(default=5.0, ge=1, le=60)
    # Play a cached "Okay." / "Got it." while the agent thinks (phase-06 §5.8)
    voice_acknowledgements: bool = True
    # Synthesize the job's questions during the greeting: replies that ask them play at once
    voice_tts_warm: bool = True
    # Reply still silent this long after the candidate finished → "One moment." (0 = never)
    voice_hold_after_ms: int = Field(default=3500, ge=0, le=10000)

    # Voice engine for screening calls. pipeline = Deepgram STT + OPENAI_MODEL + Kitten/Aura (the
    # Phase 6 chain); realtime = OpenAI Realtime speech-to-speech (one model hears and speaks;
    # trial added 2026-11-19, see docs/realtime-voice.md). The Settings page can override it.
    voice_engine: Literal["pipeline", "realtime"] = "pipeline"
    openai_realtime_model: str = "gpt-realtime-2.1-mini"
    openai_realtime_voice: str = "marin"
    # Transcribes the candidate's side for the transcript and the post-call final pass
    # gpt-4o-mini-transcribe wrote 2 of 15 lines of the first real call in Devanagari/Urdu script
    openai_realtime_transcribe_model: str = "gpt-4o-transcribe"
    realtime_vad_silence_ms: int = Field(default=600, ge=200, le=3000)
    realtime_vad_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    # Silence after the agent's audio has PLAYED (our timer; the server's idle timer counts from
    # when audio is generated, and fired mid-sentence in the first trial) → "still there?",
    # then a goodbye. Uses SILENCE_TIMEOUT_S like the pipeline.

    # Google Sheets (Phase 7, docs/google-sheets.md). The key is a PATH to a read-only mounted
    # file (secrets/google-sa.json, gitignored), never the JSON itself.
    google_service_account_json: str | None = None
    google_sheet_id: str | None = None
    google_sheet_tab: str = "Candidates"
    google_sheets_timeout_s: float = Field(default=20.0, gt=0, le=120)

    # Calling. The Settings page (app_settings, phase-08) can lower the concurrency, change the
    # window and retries and pause calling; these values are the defaults and the hard limits.
    calling_enabled: bool = True  # false = nothing dials, whatever the Settings page says
    organization_name: str | None = None  # Settings page only
    agent_introduction: str | None = None  # Settings page only; None = built-in introduction
    max_concurrent_calls: int = Field(default=1, ge=1, le=2)
    max_call_attempts: int = Field(default=3, ge=1, le=10)
    retry_interval_days: int = Field(default=2, ge=2, le=4)

    # Automatic retries (Phase 9, docs/retries.md). Defaults; the Settings page can change them.
    retry_enabled: bool = True
    max_callbacks: int = Field(default=2, ge=0, le=5)  # callbacks don't count as attempts
    retry_alternate_slots: bool = True  # alternate morning and afternoon between retries
    # Staging only: "minutes" turns the retry interval into minutes, so a real no-answer → retry
    # cycle can be tried on a tester's phone. Refused when APP_ENV=production.
    retry_interval_unit: Literal["days", "minutes"] = "days"

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

    @field_validator("telephony_sample_rate")
    @classmethod
    def _telephony_rate(cls, value: int) -> int:
        if value not in (8000, 16000, 24000):
            raise ValueError("must be 8000, 16000 or 24000")
        return value

    @field_validator("telephony_frame_bytes")
    @classmethod
    def _frame_multiple(cls, value: int) -> int:
        if value % 320:
            raise ValueError("must be a multiple of 320 bytes")
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
        if self.retry_interval_unit != "days":
            raise ValueError("RETRY_INTERVAL_UNIT=minutes is for staging only, not production")
        return self

    @property
    def longest_call_s(self) -> int:
        """The longest any call may last (concurrency slot TTL, stuck-call threshold)."""
        return max(self.max_call_duration_s, self.telephonic_max_call_duration_s)

    def for_telephonic_call(self) -> "Settings":
        """These settings with the telephonic round's call limits and silence timeout (the
        voice pipeline reads max_call_duration_s, call_wrap_up_s and silence_timeout_s)."""
        return self.model_copy(
            update={
                "max_call_duration_s": self.telephonic_max_call_duration_s,
                "call_wrap_up_s": self.telephonic_wrap_up_s,
                "silence_timeout_s": self.telephonic_silence_timeout_s,
            }
        )

    @property
    def exotel_configured(self) -> bool:
        """Everything needed to place a call and receive its callbacks and stream."""
        return bool(
            self.exotel_api_key
            and self.exotel_api_token
            and self.exotel_account_sid
            and self.exotel_subdomain
            and self.exotel_caller_id
            and self.exotel_app_id
            and self.public_backend_url
        )

    @property
    def sheets_configured(self) -> bool:
        return bool(self.google_service_account_json and self.google_sheet_id)

    def derived_secret(self, purpose: str, *, hex_only: bool = False) -> str:
        """A stable per-purpose secret derived from APP_SECRET_KEY (URL-safe, 43 chars).

        Used for the webhook and stream URL tokens, so they need no extra settings and change
        when APP_SECRET_KEY is rotated.
        """
        digest = hmac.new(
            self.app_secret_key.get_secret_value().encode(), purpose.encode(), hashlib.sha256
        ).digest()
        if hex_only:
            return digest.hex()[:48]
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def provider_configuration(self) -> dict[str, bool]:
        """Which external providers have their settings filled in (not whether they work)."""
        return {
            "openai": bool(self.openai_api_key and self.openai_model),
            "deepgram": bool(self.deepgram_api_key),
            "exotel": self.exotel_configured,
            "kitten_tts": True,  # local model with defaults; whether it loaded is in TTS status
            "google_sheets": self.sheets_configured,
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
