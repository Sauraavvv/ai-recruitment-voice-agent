"""Synthetic data for the E2E stack only (recruitment_ai_e2e): one candidate with a finished,
finalized screening call (transcript, summary, answers with quotes, one data conflict) and
one failed call. Run by start-backend.sh after the migrations."""

import asyncio
from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.database.connection import dispose_engine, get_sessionmaker, init_engine
from app.database.models import CallAttempt, Candidate, Conversation, Job

T0 = datetime.now(UTC) - timedelta(hours=2)
LINES = [
    ("assistant", "Hello, am I speaking with Priya Sharma?"),
    ("candidate", "Yes, speaking."),
    ("assistant", "Hi Priya, I'm an AI recruitment assistant calling on behalf of Seed Co about a Data Engineer role. Is this a good time for a quick five-minute conversation?"),
    ("candidate", "Sure."),
    ("assistant", "Where are you currently based?"),
    ("candidate", "Bengaluru."),
    ("assistant", "What is your notice period?"),
    ("candidate", "Thirty days."),
    ("assistant", "And your current CTC?"),
    ("candidate", "Twelve lakhs per annum."),
    ("assistant", "Got it. What are you expecting?"),
    ("candidate", "Around eighteen."),
    ("assistant", "Thank you. Just to confirm, your notice period is 30 days?"),
    ("candidate", "Actually it could be sixty days, I need to check."),
    ("assistant", "Thanks, Priya. A recruiter will follow up. Goodbye!"),
]


def meta(value, raw, seq, status="answered", **extra):
    return {"value": value, "raw_text": raw, "seq": seq, "status": status, "source": "live", **extra}


async def main() -> None:
    settings = get_settings()
    init_engine(settings.database_url.get_secret_value())
    async with get_sessionmaker()() as db:
        job = Job(job_title="Data Engineer", company_name="Seed Co", is_active=False)
        db.add(job)
        await db.flush()
        cand = Candidate(
            name="Priya Sharma",
            phone="+919876500099",
            job_id=job.id,
            applied_role="Data Engineer",
            consent_source="manual",
            consent_at=T0 - timedelta(days=1),
            current_location="Bengaluru",
            current_ctc=12.0,
            expected_ctc=18.0,
            notice_period="30 days",
            interested=True,
            screening_status="partially_completed",
        )
        db.add(cand)
        await db.flush()
        failed = CallAttempt(
            candidate_id=cand.id, attempt_number=1, attempt_type="manual", provider="exotel",
            call_status="no_answer", end_reason="no_answer", created_at=T0 - timedelta(days=1),
        )
        done = CallAttempt(
            candidate_id=cand.id, attempt_number=2, attempt_type="manual", provider="exotel",
            call_status="completed", end_reason="agent_completed", stream_id="seed",
            start_time=T0, end_time=T0 + timedelta(seconds=184), duration_seconds=184,
            provider_status="completed",
        )
        db.add_all([failed, done])
        await db.flush()
        aid = str(done.id)
        conflict = {"final_value": "60 days", "quote": "it could be sixty days", "seq": 14,
                    "reason": "confirmed during the call"}
        cand.screening_field_meta = {
            "current_location": meta("Bengaluru", "Bengaluru.", 6, call_attempt_id=aid),
            "notice_period": meta("30 days", "Thirty days.", 8, "confirmed", call_attempt_id=aid,
                                  conflict=conflict),
            "current_ctc": meta(12.0, "Twelve lakhs per annum.", 10, call_attempt_id=aid),
            "expected_ctc": meta(18.0, "Around eighteen.", 12, call_attempt_id=aid),
            "interested": meta(True, "Sure.", 4, call_attempt_id=aid),
        }
        db.add(
            Conversation(
                call_attempt_id=done.id,
                transcript=[
                    {"seq": i + 1, "speaker": s, "text": t,
                     "timestamp": (T0 + timedelta(seconds=12 * i)).isoformat(),
                     "interrupted": i == 12, "heard_text": "Thank you. Just to confirm" if i == 12 else None}
                    for i, (s, t) in enumerate(LINES)
                ],
                summary=(
                    "Priya Sharma is interested in the Data Engineer role and is based in "
                    "Bengaluru. Current CTC is 12 LPA and expected CTC is 18 LPA. The notice "
                    "period was given as 30 days, then possibly 60 days."
                ),
                extracted_data={
                    "result": {"callback": {"requested": False}},
                    "final": {
                        "fields": {"current_location": {"value": "Bengaluru"}},
                        "conflicts": {"notice_period": conflict},
                        "missing_fields": ["current_company", "total_experience", "reason_for_change"],
                    },
                    "summary_sections": {
                        "generated_by": "llm",
                        "missing_information": ["current_company", "total_experience", "reason_for_change"],
                        "callback": None,
                    },
                },
                finalized_at=T0 + timedelta(seconds=200),
            )
        )
        await db.commit()
    await dispose_engine()


asyncio.run(main())
