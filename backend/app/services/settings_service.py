"""Recruiter-editable settings (phase-08 §5.4), stored in `app_settings`.

Two rows, each a JSON object:

  general         organization name, agent introduction, calling window, max concurrent calls,
                  retry configuration, calling enabled (the global pause)
  google_sheets   the spreadsheet id and tab (admin only); empty = the .env values

Environment values are the defaults, and the hard limits stay in the environment: the
concurrency set here can't exceed MAX_CONCURRENT_CALLS. `effective()` returns a copy of the
`Settings` with the stored values applied; everything that dials or syncs uses that copy, so a
change applies at once without a restart.
"""

import re
import uuid
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.connection import get_sessionmaker
from app.database.models import AppSetting
from app.services.errors import unprocessable
from app.utils.log import get_logger

logger = get_logger(__name__)

GENERAL_KEY = "general"
SHEETS_KEY = "google_sheets"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# What an introduction template may use. {first_name} is the candidate's first name.
INTRO_PLACEHOLDERS = frozenset({"first_name", "company", "job_title", "organization"})
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
SHEET_ID = re.compile(r"^[A-Za-z0-9_-]{20,100}$")
SHEET_URL_ID = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]{20,100})")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CallingWindow(_Strict):
    days: list[str] = Field(min_length=1, max_length=7)
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)

    @field_validator("days")
    @classmethod
    def _days(cls, value: list[str]) -> list[str]:
        days = {d.strip().lower()[:3] for d in value}
        unknown = days - set(DAYS)
        if unknown:
            raise ValueError(f"unknown day(s): {', '.join(sorted(unknown))}")
        return [d for d in DAYS if d in days]  # week order, no duplicates

    @model_validator(mode="after")
    def _order(self) -> "CallingWindow":
        if self.end_hour <= self.start_hour:
            raise ValueError("end_hour must be after start_hour")
        return self


class RetryConfig(_Strict):
    """Used by the Phase 9 retry automation; editable from now on."""

    max_attempts: int = Field(ge=1, le=10)
    interval_days: int = Field(ge=2, le=4)


class GeneralSettings(_Strict):
    organization_name: str | None = Field(default=None, max_length=200)
    # None = the built-in introduction (prompts.introduction)
    agent_introduction: str | None = Field(default=None, max_length=500)
    calling: CallingWindow
    max_concurrent_calls: int = Field(ge=1, le=10)
    retry: RetryConfig
    calling_enabled: bool = True

    @field_validator("organization_name", "agent_introduction", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = " ".join(value.split())
            return value or None
        return value

    @field_validator("agent_introduction")
    @classmethod
    def _intro(cls, value: str | None) -> str | None:
        if value is None:
            return None
        names = set(_PLACEHOLDER.findall(value))
        unknown = names - INTRO_PLACEHOLDERS
        if unknown:
            allowed = ", ".join("{" + n + "}" for n in sorted(INTRO_PLACEHOLDERS))
            raise ValueError(f"unknown placeholder(s) {sorted(unknown)}; use {allowed}")
        if value.count("{") != value.count("}"):
            raise ValueError("unbalanced braces")
        # plan.md §4 Module B: the agent always says it's an AI
        if not re.search(r"\bAI\b", value):
            raise ValueError('must say the caller is an AI (include the word "AI")')
        if not value.rstrip().endswith("?"):
            raise ValueError("must end with a question (the candidate answers it)")
        return value


class GeneralUpdate(_Strict):
    """PATCH body: sections left out are unchanged."""

    organization_name: str | None = Field(default=None, max_length=200)
    agent_introduction: str | None = Field(default=None, max_length=500)
    calling: CallingWindow | None = None
    max_concurrent_calls: int | None = Field(default=None, ge=1, le=10)
    retry: RetryConfig | None = None
    calling_enabled: bool | None = None


class SheetSettings(_Strict):
    sheet_id: str | None = None
    tab: str | None = Field(default=None, max_length=100)
    changed_by: str | None = None  # user id
    changed_at: str | None = None


def defaults(settings: Settings) -> GeneralSettings:
    days = [d.strip().lower()[:3] for d in settings.calling_days.split(",") if d.strip()]
    return GeneralSettings(
        calling=CallingWindow(
            days=days or list(DAYS[:6]),
            start_hour=settings.calling_hour_start,
            end_hour=settings.calling_hour_end,
        ),
        max_concurrent_calls=settings.max_concurrent_calls,
        retry=RetryConfig(
            max_attempts=settings.max_call_attempts, interval_days=settings.retry_interval_days
        ),
    )


async def _rows(session: AsyncSession) -> dict[str, Any]:
    rows = await session.execute(
        select(AppSetting.key, AppSetting.value).where(
            AppSetting.key.in_([GENERAL_KEY, SHEETS_KEY])
        )
    )
    return {key: value for key, value in rows}


def _general(stored: Any, settings: Settings) -> GeneralSettings:
    base = defaults(settings).model_dump()
    if isinstance(stored, dict):
        base.update({k: v for k, v in stored.items() if k in GeneralSettings.model_fields})
    try:
        return GeneralSettings.model_validate(base)
    except ValueError:
        logger.warning("settings_invalid_stored", key=GENERAL_KEY)
        return defaults(settings)


def _sheets(stored: Any) -> SheetSettings:
    if not isinstance(stored, dict):
        return SheetSettings()
    try:
        return SheetSettings.model_validate(stored)
    except ValueError:
        return SheetSettings()


def apply(settings: Settings, general: GeneralSettings, sheets: SheetSettings) -> Settings:
    return settings.model_copy(
        update={
            "calling_days": ",".join(general.calling.days),
            "calling_hour_start": general.calling.start_hour,
            "calling_hour_end": general.calling.end_hour,
            # the environment value is the hard limit (Exotel channels, CPU for the voice)
            "max_concurrent_calls": min(
                general.max_concurrent_calls, settings.max_concurrent_calls
            ),
            "max_call_attempts": general.retry.max_attempts,
            "retry_interval_days": general.retry.interval_days,
            "calling_enabled": settings.calling_enabled and general.calling_enabled,
            "organization_name": general.organization_name,
            "agent_introduction": general.agent_introduction,
            "google_sheet_id": sheets.sheet_id or settings.google_sheet_id,
            "google_sheet_tab": sheets.tab or settings.google_sheet_tab,
        }
    )


async def load(session: AsyncSession, settings: Settings) -> tuple[GeneralSettings, SheetSettings]:
    rows = await _rows(session)
    return _general(rows.get(GENERAL_KEY), settings), _sheets(rows.get(SHEETS_KEY))


async def effective(session: AsyncSession, settings: Settings) -> Settings:
    """The environment settings with the stored ones applied."""
    general, sheets = await load(session, settings)
    return apply(settings, general, sheets)


async def effective_new_session(settings: Settings) -> Settings:
    """`effective()` for callers without a session (workers)."""
    async with get_sessionmaker()() as session:
        return await effective(session, settings)


async def _put(session: AsyncSession, key: str, value: dict[str, Any]) -> None:
    row = await session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value


async def update_general(
    session: AsyncSession, settings: Settings, changes: GeneralUpdate, *, user_id: uuid.UUID
) -> GeneralSettings:
    current, _ = await load(session, settings)
    sent = changes.model_dump(exclude_unset=True)
    merged = current.model_dump() | {
        k: v
        for k, v in sent.items()
        # a required section sent as null means "unchanged"; the two texts may be cleared
        if v is not None or k in {"organization_name", "agent_introduction"}
    }
    try:
        new = GeneralSettings.model_validate(merged)  # re-validates the introduction etc.
    except ValidationError as exc:
        details = [
            {"loc": ["body", *e["loc"]], "msg": e["msg"], "type": e["type"]}
            for e in exc.errors(include_input=False, include_context=False, include_url=False)
        ]
        raise unprocessable("validation_error", "Request validation failed", details) from None
    await _put(session, GENERAL_KEY, new.model_dump(mode="json"))
    await session.commit()
    changed = sorted(k for k in sent if getattr(current, k) != getattr(new, k))
    logger.info(
        "settings_updated",
        user_id=str(user_id),
        sections=changed,
        calling_enabled=new.calling_enabled if "calling_enabled" in changed else None,
    )
    return new


def parse_sheet_link(link: str) -> str | None:
    """The spreadsheet id from a Google Sheets link (…/spreadsheets/d/<id>/…) or a bare id."""
    link = link.strip()
    match = SHEET_URL_ID.search(link)
    if match:
        return match.group(1)
    return link if SHEET_ID.match(link) else None


async def update_sheet(
    session: AsyncSession, *, sheet_id: str, tab: str | None, user_id: uuid.UUID, now: str
) -> SheetSettings:
    value = SheetSettings(sheet_id=sheet_id, tab=tab, changed_by=str(user_id), changed_at=now)
    await _put(session, SHEETS_KEY, value.model_dump(mode="json"))
    await session.commit()
    logger.info("sheet_changed", user_id=str(user_id), sheet_id=sheet_id, tab=tab)
    return value


def render_introduction(
    template: str, *, first_name: str, company: str, job_title: str, organization: str | None
) -> str:
    values = {
        "first_name": first_name,
        "company": company,
        "job_title": job_title,
        "organization": organization or company,
    }
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template)
