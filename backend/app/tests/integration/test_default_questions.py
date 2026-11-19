from typing import Any

from httpx import AsyncClient

URL = "/api/v1/jobs/default-screening-questions"


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
    authed: AsyncClient, active_job: dict[str, Any]
) -> None:
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
