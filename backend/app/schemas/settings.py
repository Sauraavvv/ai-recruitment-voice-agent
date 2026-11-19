from datetime import datetime

from pydantic import BaseModel

from app.schemas.integrations import SheetsStatus
from app.services.settings_service import GeneralSettings


class SettingsLimits(BaseModel):
    """Fixed in the environment; shown read-only."""

    max_concurrent_calls: int  # MAX_CONCURRENT_CALLS: the most the Settings page may set
    timezone: str  # APP_TIMEZONE: the calling window and all dates
    calling_enabled_env: bool  # CALLING_ENABLED=false pauses calling whatever is set here
    voice_engine_env: str  # VOICE_ENGINE: used when the Settings page leaves it unset
    realtime_model: str  # OPENAI_REALTIME_MODEL


class IntroductionPreview(BaseModel):
    text: str  # the opening line as the agent would say it to a sample candidate
    sample_first_name: str
    company: str
    job_title: str
    organization: str | None
    built_in: bool  # no template set: the built-in introduction


class SettingsOut(BaseModel):
    general: GeneralSettings
    limits: SettingsLimits
    introduction: IntroductionPreview
    calling_now: bool  # inside the window and not paused, right now


class ProviderStatus(BaseModel):
    name: str
    label: str
    configured: bool
    reachable: bool | None
    message: str | None
    detail: str | None
    last_checked: datetime


class StatusOut(BaseModel):
    providers: list[ProviderStatus]
    google_sheets: SheetsStatus
