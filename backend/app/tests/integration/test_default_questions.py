import uuid
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.tests.conftest import TEST_PASSWORD

URL = "/api/v1/jobs/default-screening-questions"


async def _owns_original_jobs(user: Any, db: AsyncSession) -> None:
    """Make the test user's company the oldest one, the owner of the original flow's jobs.
    (Companies made in one test share the transaction's clock, so it is set explicitly.)"""
    user.organization.created_at = datetime(2020, 1, 1, tzinfo=UTC)
    await db.flush()


async def _defaults(authed: AsyncClient) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = (await authed.get(URL)).json()["data"]
    return data


async def test_edit_remove_and_add(authed: AsyncClient) -> None:
    questions = await _defaults(authed)
    notice = next(q for q in questions if q["key"] == "notice_period")
    notice.update(prompt="  How soon can you join?  ", required=False)
    edited = [q for q in questions if q["key"] != "reason_for_change"]
    edited.append({"key": "q_laptop", "prompt": "Do you have a laptop?", "type": "boolean"})

    response = await authed.put(URL, json={"questions": edited})
    assert response.status_code == 200
    after = await _defaults(authed)
    assert [q["key"] for q in after] == [q["key"] for q in edited]
    notice_after = next(q for q in after if q["key"] == "notice_period")
    assert notice_after["prompt"] == "How soon can you join?"
    assert notice_after["required"] is False
    assert after[-1]["type"] == "boolean"


async def test_rejects_bad_lists(authed: AsyncClient) -> None:
    assert (await authed.put(URL, json={"questions": []})).status_code == 422
    empty = {"questions": [{"key": "notice_period", "prompt": "   "}]}
    assert (await authed.put(URL, json=empty)).status_code == 422
    retyped = {"questions": [{"key": "current_ctc", "prompt": "CTC?", "type": "string"}]}
    assert (await authed.put(URL, json=retyped)).status_code == 422
    duplicate = {"questions": [{"key": "q_a", "prompt": "A?"}, {"key": "q_a", "prompt": "B?"}]}
    assert (await authed.put(URL, json=duplicate)).status_code == 422


async def test_jobs_using_defaults_follow_edits(
    authed: AsyncClient, active_job: dict[str, Any], user: Any, db_session: AsyncSession
) -> None:
    await _owns_original_jobs(user, db_session)
    custom = (
        await authed.post(
            "/api/v1/jobs",
            json={
                "job_title": "QA",
                "company_name": "Test Co",
                "screening_questions": [{"key": "q_laptop", "prompt": "Laptop?"}],
            },
        )
    ).json()["data"]
    # The defaults in another order still count as using the defaults
    reordered = list(reversed(active_job["screening_questions"]))
    older = (
        await authed.post(
            "/api/v1/jobs",
            json={"job_title": "Ops", "company_name": "Co", "screening_questions": reordered},
        )
    ).json()["data"]

    questions = await _defaults(authed)
    for q in questions:
        if q["key"] == "current_ctc":
            q["prompt"] = "What do you earn now?"
    result = (await authed.put(URL, json={"questions": questions})).json()["data"]
    assert result["jobs_updated"] == 2

    for job_id in (active_job["id"], older["id"]):
        job = (await authed.get(f"/api/v1/jobs/{job_id}")).json()["data"]
        assert job["screening_questions"] == result["questions"]
    other = (await authed.get(f"/api/v1/jobs/{custom['id']}")).json()["data"]
    assert other["screening_questions"] == custom["screening_questions"]

    # New jobs start from the edited list; a reset brings back the originals everywhere
    new = (
        await authed.post("/api/v1/jobs", json={"job_title": "Dev", "company_name": "Co"})
    ).json()["data"]
    assert new["screening_questions"] == result["questions"]

    reset = (await authed.delete(URL)).json()["data"]
    assert reset["jobs_updated"] == 3
    ctc = next(q for q in reset["questions"] if q["key"] == "current_ctc")
    assert ctc["prompt"] == "What is your current CTC?"
    assert len(await _defaults(authed)) == 10


async def test_requires_login(api: AsyncClient) -> None:
    assert (await api.put(URL, json={"questions": []})).status_code == 401


async def test_each_company_has_its_own(
    authed: AsyncClient, active_job: dict[str, Any], user: Any, db_session: AsyncSession
) -> None:
    """Company B's edits change neither A's list nor A's (original-flow) jobs, and B starts
    from the originals, not from A's edits."""
    await _owns_original_jobs(user, db_session)
    questions = await _defaults(authed)
    a_list = [q for q in questions if q["key"] != "reason_for_change"]
    assert (await authed.put(URL, json={"questions": a_list})).status_code == 200

    await authed.post("/api/v1/auth/logout")
    signup = await authed.post(
        "/api/v1/auth/signup",
        json={
            "organization_name": "Company B",
            "name": "B Owner",
            "email": f"owner-{uuid.uuid4().hex[:8]}@b.example",
            "password": TEST_PASSWORD,
        },
    )
    assert signup.status_code == 201, signup.text
    b_list = await _defaults(authed)
    assert len(b_list) == 10
    b_list[0]["prompt"] = "Company B's own wording?"
    result = (await authed.put(URL, json={"questions": b_list})).json()["data"]
    assert result["jobs_updated"] == 0
    assert (await _defaults(authed))[0]["prompt"] == "Company B's own wording?"
    job = (await authed.get(f"/api/v1/jobs/{active_job['id']}")).json()["data"]
    assert job["screening_questions"] == a_list
