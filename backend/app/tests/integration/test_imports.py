"""Import end to end against the real database (P1-AC1, AC2, AC3)."""

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ImportBatch

FIXTURES = Path(__file__).parent.parent / "fixtures" / "imports"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def upload(client: AsyncClient, name: str, **data: str) -> Any:
    content_type = XLSX if name.endswith(".xlsx") else "text/csv"
    files = {"file": (name, (FIXTURES / name).read_bytes(), content_type)}
    return await client.post("/api/v1/candidates/import", files=files, data=data)


async def confirm(client: AsyncClient, import_id: str) -> Any:
    return await client.post(
        f"/api/v1/candidates/import/{import_id}/confirm", json={"consent_attested": True}
    )


def counts(report: dict[str, Any]) -> tuple[int, int, int, int, int]:
    return (
        report["total_rows"],
        report["valid_candidates"],
        report["duplicate_candidates"],
        report["invalid_candidates"],
        report["imported_candidates"],
    )


async def test_valid_5_csv(authed: AsyncClient, active_job: dict[str, Any]) -> None:
    preview = await upload(authed, "valid_5.csv")
    assert preview.status_code == 201, preview.text
    data = preview.json()["data"]
    assert data["status"] == "preview"
    assert data["job_id"] == active_job["id"]
    assert data["unmapped_columns"] == []
    assert counts(data["report"]) == (5, 5, 0, 0, 0)
    assert len(data["rows"]) == 5
    # Nothing is saved until confirm.
    assert (await authed.get("/api/v1/candidates")).json()["meta"]["total"] == 0

    result = await confirm(authed, data["id"])
    assert result.status_code == 200
    assert result.json()["data"]["status"] == "confirmed"
    assert counts(result.json()["data"]["report"]) == (5, 5, 0, 0, 5)

    listed = (await authed.get("/api/v1/candidates", params={"sort": "name"})).json()
    assert listed["meta"]["total"] == 5
    first = listed["data"][0]
    assert first["phone"] == "+919000000001"
    assert first["consent_source"] == "recruiter_attested_import"
    assert first["applied_role"] == "Backend Developer"
    assert first["current_location"] == "Pune"
    assert first["total_experience"] == 1.0

    # Result endpoint keeps the report but no longer holds row data.
    stored = (await authed.get(f"/api/v1/candidates/import/{data['id']}")).json()["data"]
    assert stored["status"] == "confirmed"
    assert stored["rows"] == []
    assert stored["report"]["imported_candidates"] == 5


async def test_mixed_10_xlsx_matches_plan_example(
    authed: AsyncClient, active_job: dict[str, Any]
) -> None:
    preview = (await upload(authed, "mixed_10.xlsx")).json()["data"]
    assert counts(preview["report"]) == (10, 8, 1, 1, 0)
    errors = preview["report"]["errors"]
    assert {"row": 10, "field": "phone", "message": "Same phone as row 2"} in errors
    assert {"row": 11, "field": "phone", "message": "Phone number is too short"} in errors

    result = (await confirm(authed, preview["id"])).json()["data"]
    assert counts(result["report"]) == (10, 8, 1, 1, 8)
    assert (await authed.get("/api/v1/candidates")).json()["meta"]["total"] == 8


async def test_reimport_flags_existing_and_changes_nothing(
    authed: AsyncClient, active_job: dict[str, Any], db_session: AsyncSession
) -> None:
    first = (await upload(authed, "valid_5.csv")).json()["data"]
    await confirm(authed, first["id"])
    # Simulate screening data gathered by a call, which a re-import must not overwrite.
    await db_session.execute(
        text("UPDATE candidates SET current_location = 'Gurgaon' WHERE phone = '+919000000001'")
    )
    before = (await authed.get("/api/v1/candidates", params={"sort": "name"})).json()["data"]

    second = (await upload(authed, "valid_5.csv")).json()["data"]
    assert counts(second["report"]) == (5, 0, 5, 0, 0)
    assert {r["status"] for r in second["rows"]} == {"duplicate_existing"}
    ids = {r["existing_candidate_id"] for r in second["rows"]}
    assert ids == {c["id"] for c in before}

    result = (await confirm(authed, second["id"])).json()["data"]
    assert result["report"]["imported_candidates"] == 0
    after = (await authed.get("/api/v1/candidates", params={"sort": "name"})).json()["data"]
    assert after == before  # same values and same updated_at
    assert after[0]["current_location"] == "Gurgaon"


async def test_remap_columns(authed: AsyncClient, active_job: dict[str, Any]) -> None:
    preview = (await upload(authed, "semicolon.csv")).json()["data"]
    assert counts(preview["report"]) == (2, 2, 0, 0, 0)
    mapping = preview["column_mapping"]
    assert mapping["email"] == 3
    assert mapping["total_experience"] == 4

    url = f"/api/v1/candidates/import/{preview['id']}/mapping"
    remapped = await authed.put(url, json={"column_mapping": {**mapping, "applied_role": None}})
    assert remapped.status_code == 200
    data = remapped.json()["data"]
    assert data["report"]["invalid_candidates"] == 2
    assert "Designation" in data["unmapped_columns"]

    clash = await authed.put(url, json={"column_mapping": {"name": 0, "phone": 0}})
    assert clash.status_code == 422
    assert clash.json()["error"]["code"] == "invalid_mapping"


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("numeric_phones.xlsx", (3, 3, 0, 0, 0)),
        ("scientific_phone.xlsx", (2, 1, 0, 1, 0)),
        ("cp1252.csv", (1, 1, 0, 0, 0)),
        ("semicolon.csv", (2, 2, 0, 0, 0)),
    ],
)
async def test_fixture_previews(
    authed: AsyncClient,
    active_job: dict[str, Any],
    fixture: str,
    expected: tuple[int, int, int, int, int],
) -> None:
    response = await upload(authed, fixture)
    assert response.status_code == 201, response.text
    assert counts(response.json()["data"]["report"]) == expected


async def test_scientific_notation_message(authed: AsyncClient, active_job: dict[str, Any]) -> None:
    rows = (await upload(authed, "scientific_phone.xlsx")).json()["data"]["rows"]
    assert "format the phone column as text" in rows[0]["errors"][0]["message"]


async def test_wrong_file_type(authed: AsyncClient, active_job: dict[str, Any]) -> None:
    response = await upload(authed, "wrong_type.pdf")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_file_type"
    assert ".xlsx" in response.json()["error"]["message"]


async def test_confirm_rules(
    authed: AsyncClient, active_job: dict[str, Any], db_session: AsyncSession
) -> None:
    preview = (await upload(authed, "valid_5.csv")).json()["data"]
    url = f"/api/v1/candidates/import/{preview['id']}/confirm"

    no_consent = await authed.post(url, json={"consent_attested": False})
    assert no_consent.status_code == 422
    assert no_consent.json()["error"]["code"] == "consent_required"

    assert (await confirm(authed, preview["id"])).status_code == 200
    again = await confirm(authed, preview["id"])
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "import_already_confirmed"

    stale = (await upload(authed, "cp1252.csv")).json()["data"]
    await db_session.execute(
        update(ImportBatch)
        .where(ImportBatch.id == stale["id"])
        .values(created_at=text("now() - interval '25 hours'"))
    )
    expired = await confirm(authed, stale["id"])
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "import_expired"


async def test_expiry_job_clears_rows(
    authed: AsyncClient, active_job: dict[str, Any], db_session: AsyncSession
) -> None:
    from app.services.import_service import expire_stale_previews

    preview = (await upload(authed, "cp1252.csv")).json()["data"]
    await db_session.execute(
        update(ImportBatch)
        .where(ImportBatch.id == preview["id"])
        .values(created_at=text("now() - interval '25 hours'"))
    )
    assert await expire_stale_previews(db_session) == 1
    batch = await db_session.get(ImportBatch, preview["id"])
    assert batch is not None
    await db_session.refresh(batch)
    assert batch.status == "expired"
    assert batch.rows is None


async def test_upload_needs_active_job(authed: AsyncClient) -> None:
    response = await upload(authed, "valid_5.csv")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_active_job"
