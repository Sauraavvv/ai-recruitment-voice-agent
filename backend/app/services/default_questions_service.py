"""The default screening questions, as the recruiters have edited them.

The ten standard questions in code are the starting point. Recruiters can reword, reorder,
remove and add questions; the edited list lives in app_settings. Standard keys keep their
types because each answer fills a candidate field.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AppSetting, Job
from app.schemas.job import ScreeningQuestion, default_screening_questions

SETTING_KEY = "default_questions"


def _dump(questions: list[ScreeningQuestion]) -> list[dict[str, Any]]:
    return [q.model_dump(exclude_none=True) for q in questions]


def _load(row: AppSetting | None) -> list[ScreeningQuestion]:
    # Only a list is a saved question list; anything else means "the originals"
    if row is None or not isinstance(row.value, list) or not row.value:
        return default_screening_questions()
    return [ScreeningQuestion.model_validate(q) for q in row.value]


def _same_questions(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> bool:
    """Same questions, in any order."""
    by_key = {q["key"]: q for q in b}
    return len(a) == len(b) == len(by_key) and all(by_key.get(q["key"]) == q for q in a)


async def get(session: AsyncSession) -> list[ScreeningQuestion]:
    return _load(await session.get(AppSetting, SETTING_KEY))


async def _replace(
    session: AsyncSession, questions: list[ScreeningQuestion] | None
) -> tuple[list[ScreeningQuestion], int]:
    """Store the new list (None: back to the originals). Jobs still asking exactly the old
    defaults, in any order, switch to the new list."""
    row = await session.get(AppSetting, SETTING_KEY)
    old = _dump(_load(row))
    new_questions = questions if questions is not None else default_screening_questions()
    new = _dump(new_questions)

    if questions is None:
        if row is not None:
            await session.delete(row)
    elif row is None:
        session.add(AppSetting(key=SETTING_KEY, value=new))
    else:
        row.value = new

    updated = 0
    if new != old:
        jobs = (await session.execute(select(Job))).scalars().all()
        for job in jobs:
            if _same_questions(job.screening_questions, old):
                job.screening_questions = new
                updated += 1
    await session.commit()
    return new_questions, updated


async def update(
    session: AsyncSession, questions: list[ScreeningQuestion]
) -> tuple[list[ScreeningQuestion], int]:
    return await _replace(session, questions)


async def reset(session: AsyncSession) -> tuple[list[ScreeningQuestion], int]:
    """Back to the ten original questions."""
    return await _replace(session, None)
