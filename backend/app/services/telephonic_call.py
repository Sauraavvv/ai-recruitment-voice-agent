"""What a telephonic round call is about (phase-11 step 6b): the role, the JD, the pinned
question set and what the candidate already answered on an earlier call of the same round.

- The firm (the organization) is who the agent calls for. The client is named only when it
  isn't confidential (decision 2); for a confidential client its name is also taken out of the
  JD, which may mention it.
- The questions come from the attempt's pinned set (frozen once approved), so a later approval
  never changes a call that was queued earlier.
- A callback or retry of the round resumes: answers from earlier calls that asked the same set
  are loaded, and the agent starts at the first question not yet answered.
"""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.telephonic_prompts import RoundQuestion, TelephonicContext
from app.database.models import (
    CallAttempt,
    CallAttemptType,
    CallPurpose,
    Candidate,
    Client,
    Conversation,
    Organization,
    QuestionSet,
    Requirement,
)
from app.services.screening_job import WORK_MODE_WORDS, experience_text

HIDDEN_CLIENT = "our client"
# Kept from earlier calls (best first). "not_asked" and "dont_know" are asked again on the next
# call (as screening asks an unknown field again); a refusal stays a refusal.
ANSWER_RANK = {"answered": 3, "partial": 2, "declined": 1}
_SUFFIXES = r"private\s+limited|pvt\.?\s*ltd\.?|ltd\.?|limited|llp|inc\.?|llc|corp\.?|corporation"
_LEGAL_SUFFIX = re.compile(rf"[\s,]+(?:{_SUFFIXES})$", re.IGNORECASE)


def client_names(name: str) -> list[str]:
    """The client's name as a JD may write it: in full, and without "Pvt Ltd" and the like."""
    full = " ".join(name.split())
    short = _LEGAL_SUFFIX.sub("", full).strip()
    return [n for n in dict.fromkeys([full, short]) if len(n) >= 3]


def hide_client(text: str, names: list[str], *, replacement: str = HIDDEN_CLIENT) -> str:
    """`text` with every mention of the client replaced: any case, whole words, with or without
    a legal suffix ("Acme", "ACME", "Acme Pvt. Ltd.")."""
    for name in sorted(names, key=len, reverse=True):
        words = r"\s+".join(map(re.escape, name.split()))
        pattern = rf"(?<!\w){words}(?:[\s,]+(?:{_SUFFIXES}))?(?!\w)"
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def best_answers(answer_lists: list[list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Merge the answers of earlier calls, oldest first: per question the best status wins
    (answered > partial > declined); a later call wins a tie."""
    out: dict[str, dict[str, Any]] = {}
    for answers in answer_lists:
        for answer in answers:
            qid = str(answer.get("question_id") or "")
            rank = ANSWER_RANK.get(str(answer.get("status") or ""), 0)
            if qid and rank and rank >= ANSWER_RANK.get(str(out.get(qid, {}).get("status")), 0):
                out[qid] = dict(answer)
    return out


def open_round(
    calls: list[tuple[int, list[dict[str, Any]]]], *, callback: bool = False
) -> list[tuple[int, list[dict[str, Any]]]]:
    """The earlier calls (oldest first) that belong to the round still open. A call that asked
    every question finished its round, so the next call starts a new one ("Call again" after a
    done round asks everything again). A call cut short leaves it open, and a callback always
    continues the call before it."""
    out: list[tuple[int, list[dict[str, Any]]]] = []
    for i, (number, answers) in enumerate(calls):
        out.append((number, answers))
        finished = bool(answers) and all(a.get("status") != "not_asked" for a in answers)
        if finished and not (callback and i == len(calls) - 1):
            out = []
    return out


async def earlier_calls(
    session: AsyncSession, attempt: CallAttempt
) -> list[tuple[int, list[dict[str, Any]]]]:
    """Answers of the earlier calls of the same round (same question set), oldest first."""
    rows = await session.execute(
        select(CallAttempt.attempt_number, Conversation.extracted_data)
        .select_from(Conversation)
        .join(CallAttempt, CallAttempt.id == Conversation.call_attempt_id)
        .where(
            CallAttempt.candidate_id == attempt.candidate_id,
            CallAttempt.purpose == CallPurpose.TELEPHONIC.value,
            CallAttempt.question_set_id == attempt.question_set_id,
            CallAttempt.id != attempt.id,
            CallAttempt.attempt_number < attempt.attempt_number,
        )
        .order_by(CallAttempt.attempt_number)
    )
    calls = []
    for number, data in rows.all():
        answers = ((data or {}).get("telephonic") or {}).get("answers")
        if isinstance(answers, list):
            calls.append((int(number), [a for a in answers if isinstance(a, dict)]))
    return open_round(calls, callback=attempt.attempt_type == CallAttemptType.CALLBACK)


async def _prior_answers(session: AsyncSession, attempt: CallAttempt) -> dict[str, dict[str, Any]]:
    return best_answers([answers for _number, answers in await earlier_calls(session, attempt)])


async def for_attempt(session: AsyncSession, attempt: CallAttempt) -> TelephonicContext:
    """The context of a telephonic round attempt. Raises ValueError when what the call needs
    is gone (no pinned set, not a requirement candidate)."""
    if attempt.question_set_id is None:
        raise ValueError("telephonic attempt without a question set")
    question_set = await session.get(QuestionSet, attempt.question_set_id)
    candidate = await session.get(Candidate, attempt.candidate_id)
    if question_set is None or candidate is None or candidate.requirement_id is None:
        raise ValueError("telephonic attempt without its question set or requirement")
    requirement = await session.get(Requirement, candidate.requirement_id)
    if requirement is None:
        raise ValueError("requirement not found")
    ctx = await for_question_set(session, requirement, question_set)
    ctx.prior_answers = await _prior_answers(session, attempt)
    return ctx


async def for_question_set(
    session: AsyncSession, requirement: Requirement, question_set: QuestionSet
) -> TelephonicContext:
    """The round's context for a requirement and one of its question sets (no candidate:
    nothing answered yet). Also used by the latency check, which places no call."""
    client = await session.get(Client, requirement.client_id)
    organization = await session.get(Organization, requirement.organization_id)

    confidential = client is None or client.is_confidential
    jd = requirement.job_description or ""
    if client is not None and confidential:
        jd = hide_client(jd, client_names(client.name))
    location = requirement.location
    if requirement.work_mode:
        mode = WORK_MODE_WORDS.get(requirement.work_mode, requirement.work_mode)
        location = f"{location} ({mode})" if location else mode
    return TelephonicContext(
        firm=organization.name if organization else "",
        client_name=None if confidential or client is None else client.name,
        job_title=requirement.title,
        location=location,
        experience=experience_text(requirement),
        skills=list(requirement.skills or []),
        job_description=jd.strip(),
        requirement_id=str(requirement.id),
        question_set_id=str(question_set.id),
        version=question_set.version,
        questions=[
            RoundQuestion(
                id=str(q.get("id") or f"q{n}"),
                text=str(q.get("text") or ""),
                type=str(q.get("type") or "skill"),
                rubric=str(q.get("rubric") or ""),
                weight=int(q.get("weight") or 2),
            )
            for n, q in enumerate(question_set.questions or [], start=1)
            if str(q.get("text") or "").strip()
        ],
    )


def call_kind(attempt_type: str, prior: dict[str, dict[str, Any]]) -> str:
    """first | callback (they asked us to call back) | resume (an earlier call left answers)."""
    if attempt_type == CallAttemptType.CALLBACK:
        return "callback"
    return "resume" if prior else "first"
