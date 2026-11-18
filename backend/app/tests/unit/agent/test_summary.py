"""Summary guard (phase plan 5.10)."""

from app.agent.conversation_manager import ConversationManager
from app.agent.state import EndReason
from app.providers.llm.base import LLMTimeoutError
from app.services.summary_service import MAX_CHARS, generate_summary
from app.tests.unit.agent.stub_llm import CANDIDATE, JOB, FixedClock, ScriptedLLM

PRIOR = {
    "interested": True,
    "current_location": "Pune",
    "total_experience": 5.0,
    "current_ctc": 12.0,
    "expected_ctc": 16.0,
}


async def result(callback: bool = False):  # type: ignore[no-untyped-def]
    m = ConversationManager(JOB, CANDIDATE, ScriptedLLM(), FixedClock(), prior_fields=PRIOR)
    m.state.fields["current_company"].status = m.state.fields["current_company"].status.DECLINED
    if callback:
        m.state.callback.requested = True
        m.state.callback.time_text = "tomorrow evening"
    return await m.end(EndReason.HANGUP)


async def test_llm_narrative_with_deterministic_tail() -> None:
    llm = ScriptedLLM(["Rahul is based in Pune with 5 years of experience."])
    s = await generate_summary(
        await result(True), candidate_name="Rahul Sharma", job_title="Dev", llm=llm
    )
    assert s.generated_by == "llm"
    assert s.text.startswith("Rahul is based in Pune")
    assert "Missing:" in s.text and "Callback requested (tomorrow evening)" in s.text
    assert s.compensation == "current 12 LPA, expected 16 LPA"
    assert "declined" not in s.missing_information


async def test_judgment_is_regenerated_once() -> None:
    llm = ScriptedLLM(["Rahul is a strong candidate.", "Rahul has 5 years of experience."])
    s = await generate_summary(await result(), candidate_name="Rahul", job_title="Dev", llm=llm)
    assert s.narrative == "Rahul has 5 years of experience."
    assert "judged the candidate" in llm.calls[-1][-1].content


async def test_gendered_pronoun_is_rewritten() -> None:
    # The name doesn't tell us the candidate's gender (live call 2026-11-19 said "He")
    llm = ScriptedLLM(["He works in Pune.", "Rahul works in Pune."])
    s = await generate_summary(await result(), candidate_name="Rahul", job_title="Dev", llm=llm)
    assert s.narrative == "Rahul works in Pune."
    assert "gendered pronoun" in llm.calls[-1][-1].content


async def test_gendered_twice_falls_back_to_facts() -> None:
    llm = ScriptedLLM(["She works in Pune.", "Her CTC is 12 LPA."])
    s = await generate_summary(await result(), candidate_name="Asha", job_title="Dev", llm=llm)
    assert s.generated_by == "deterministic"


async def test_judgment_twice_falls_back_to_facts() -> None:
    llm = ScriptedLLM(["A good fit.", "I recommend him."])
    s = await generate_summary(await result(), candidate_name="Rahul", job_title="Dev", llm=llm)
    assert s.generated_by == "deterministic" and s.narrative is None
    assert "Experience: total 5 years" in s.text


async def test_llm_failure_falls_back() -> None:
    llm = ScriptedLLM([LLMTimeoutError("t")])
    s = await generate_summary(await result(), candidate_name="Rahul", job_title="Dev", llm=llm)
    assert s.generated_by == "deterministic"


async def test_length_capped() -> None:
    llm = ScriptedLLM(["word " * 400])
    s = await generate_summary(await result(True), candidate_name="Rahul", job_title="Dev", llm=llm)
    assert len(s.text) <= MAX_CHARS and s.text.endswith("(tomorrow evening).")
