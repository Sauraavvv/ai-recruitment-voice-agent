from typing import Any

from httpx import AsyncClient


async def test_first_job_is_active_with_standard_questions(
    authed: AsyncClient, active_job: dict[str, Any]
) -> None:
    keys = [q["key"] for q in active_job["screening_questions"]]
    assert keys == [
        "current_location",
        "current_company",
        "total_experience",
        "relevant_experience",
        "current_ctc",
        "expected_ctc",
        "notice_period",
        "reason_for_change",
        "interested",
        "interview_availability",
    ]
    active = await authed.get("/api/v1/jobs/active")
    assert active.json()["data"]["id"] == active_job["id"]


async def test_only_one_job_can_be_active(authed: AsyncClient, active_job: dict[str, Any]) -> None:
    second = (
        await authed.post("/api/v1/jobs", json={"job_title": "QA", "company_name": "Test Co"})
    ).json()["data"]
    assert second["is_active"] is False

    activated = await authed.post(f"/api/v1/jobs/{second['id']}/activate")
    assert activated.json()["data"]["is_active"] is True

    jobs = (await authed.get("/api/v1/jobs")).json()["data"]
    assert [j["id"] for j in jobs if j["is_active"]] == [second["id"]]


async def test_update_job_and_question_rules(
    authed: AsyncClient, active_job: dict[str, Any]
) -> None:
    url = f"/api/v1/jobs/{active_job['id']}"
    questions = [
        {"key": "expected_ctc", "prompt": "Expected salary?", "type": "number", "unit": "LPA"},
        {"key": "has_laptop", "prompt": "Do you have a laptop?", "type": "boolean"},
    ]
    response = await authed.patch(
        url, json={"job_description": "Build APIs.", "screening_questions": questions}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["job_description"] == "Build APIs."
    assert [q["key"] for q in data["screening_questions"]] == ["expected_ctc", "has_laptop"]
    assert data["job_title"] == "Backend Developer"  # untouched

    wrong_type = [{"key": "expected_ctc", "prompt": "?", "type": "string"}]
    assert (await authed.patch(url, json={"screening_questions": wrong_type})).status_code == 422
    duplicate = [{"key": "a", "prompt": "?"}, {"key": "a", "prompt": "?"}]
    assert (await authed.patch(url, json={"screening_questions": duplicate})).status_code == 422
    too_long = {"agent_instructions": "x" * 4001}
    assert (await authed.patch(url, json=too_long)).status_code == 422


async def test_unknown_job_is_404(authed: AsyncClient) -> None:
    response = await authed.get("/api/v1/jobs/00000000-0000-0000-0000-000000000009")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"
