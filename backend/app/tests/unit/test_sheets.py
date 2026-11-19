"""Sheet row mapping and the upsert logic (phase-07 P7-T6 to P7-T8), with a fake sheet."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.services.sheet_mapping import HEADERS, to_sheet_row
from app.services.sheets_service import (
    HeaderMismatchError,
    SheetsError,
    check_blocking,
    classify,
    upsert_blocking,
)
from app.tests.unit.fake_sheet import FakeSheetClient

IST = ZoneInfo("Asia/Kolkata")
CID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def candidate(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "id": CID,
        "name": "Asha Rao",
        "phone": "+919000009070",
        "email": None,
        "applied_role": "Backend Developer",
        "current_location": "Pune",
        "current_company": '=HYPERLINK("http://evil","x")',
        "total_experience": 5.0,
        "relevant_experience": 3.5,
        "current_ctc": 12.5,
        "expected_ctc": None,
        "notice_period": "30 days",
        "reason_for_change": None,
        "interested": True,
        "interview_availability": "Monday after 4 pm",
        "screening_status": "partially_completed",
        "updated_at": datetime(2026, 11, 19, 6, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def attempt(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "call_status": "no_answer",
        "start_time": None,
        "end_time": datetime(2026, 11, 19, 5, 0, tzinfo=UTC),
        "created_at": datetime(2026, 11, 19, 4, 59, tzinfo=UTC),
        "updated_at": datetime(2026, 11, 19, 7, 30, tzinfo=UTC),
        "next_retry_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def row(**kwargs: Any) -> list[Any]:
    return to_sheet_row(
        kwargs.pop("candidate", candidate()),
        kwargs.pop("attempt", attempt()),
        kwargs.pop("conversation", None),
        kwargs.pop("count", 1),
        frontend_url="https://app.example.com/",
        tz=IST,
    )


def test_row_has_the_23_columns_in_order() -> None:
    r = row(conversation=SimpleNamespace(summary="Asha is in Pune.", updated_at=None))
    assert len(HEADERS) == len(r) == 23
    by = dict(zip(HEADERS, r, strict=True))
    assert by["Candidate ID"] == str(CID)
    assert by["Phone Number"] == "+919000009070"  # RAW keeps the +
    assert by["Email"] == "" and by["Expected CTC (LPA)"] == "" and by["Reason for Change"] == ""
    assert by["Total Experience (Years)"] == 5 and by["Relevant Experience (Years)"] == 3.5
    assert by["Current CTC (LPA)"] == 12.5
    assert by["Interested"] == "Yes"
    assert by["Call Status"] == "No answer"
    assert by["Screening Status"] == "Partially completed"
    assert by["Attempt Count"] == 1
    assert by["Last Call Date"] == "2026-11-19 10:30"  # IST
    assert by["Next Retry Date"] == ""
    assert by["Call Summary"] == "Asha is in Pune."
    assert by["Transcript Reference"] == f"https://app.example.com/candidates/{CID}"
    assert by["Last Updated"] == "2026-11-19 13:00"  # the latest of candidate/attempt, IST


def test_formula_like_text_is_kept_as_text() -> None:
    by = dict(zip(HEADERS, row(), strict=True))
    assert by["Current Company"] == '=HYPERLINK("http://evil","x")'  # written RAW, never parsed


def test_booleans_and_missing_values() -> None:
    assert (
        dict(zip(HEADERS, row(candidate=candidate(interested=False)), strict=True))["Interested"]
        == "No"
    )
    no_calls = row(candidate=candidate(interested=None), attempt=None, count=0)
    by = dict(zip(HEADERS, no_calls, strict=True))
    assert by["Interested"] == "" and by["Call Status"] == "" and by["Last Call Date"] == ""
    assert by["Call Summary"] == "" and by["Attempt Count"] == 0


def test_next_retry_date_only_for_a_scheduled_attempt() -> None:
    when = datetime(2026, 11, 21, 6, 30, tzinfo=UTC)
    scheduled = attempt(call_status="retry_scheduled", next_retry_at=when)
    by = dict(zip(HEADERS, row(attempt=scheduled), strict=True))
    assert by["Next Retry Date"] == "2026-11-21 12:00"
    assert by["Last Call Date"] == ""  # a scheduled attempt hasn't been dialed


# --- Upsert --------------------------------------------------------------------------------------


def r(cid: str, name: str = "x") -> list[Any]:
    return [cid, name, *[""] * 21]


def test_empty_sheet_gets_the_header_then_rows_are_appended() -> None:
    sheet = FakeSheetClient()
    result = upsert_blocking(sheet, {"a": r("a"), "b": r("b")})  # type: ignore[arg-type]
    assert sheet.rows[0] == HEADERS and sheet.header_writes == 1
    assert [x[0] for x in sheet.data()] == ["a", "b"]
    assert result.appended == ["a", "b"] and result.updated == []


def test_existing_row_is_updated_in_place_after_a_manual_sort() -> None:
    sheet = FakeSheetClient()
    upsert_blocking(sheet, {c: r(c, "old") for c in ("c", "a", "b")})  # type: ignore[arg-type]
    sheet.sort_by(0, reverse=True)  # someone sorted the sheet by hand
    result = upsert_blocking(sheet, {"a": r("a", "new")})  # type: ignore[arg-type]
    assert result.updated == ["a"] and result.appended == []
    assert sheet.row_for("a")[1] == "new"
    assert [x[0] for x in sheet.data()] == ["c", "b", "a"]  # order kept, nothing duplicated


def test_repeated_upserts_never_duplicate() -> None:
    sheet = FakeSheetClient()
    for i in range(5):
        upsert_blocking(sheet, {"a": r("a", f"v{i}")})  # type: ignore[arg-type]
    assert len(sheet.data()) == 1 and sheet.row_for("a")[1] == "v4"
    assert sheet.header_writes == 1


def test_header_mismatch_stops_all_writes() -> None:
    edited = list(HEADERS)
    edited[3] = "E-mail"
    sheet = FakeSheetClient([edited, r("a")])
    with pytest.raises(HeaderMismatchError) as err:
        upsert_blocking(sheet, {"a": r("a", "new"), "b": r("b")})  # type: ignore[arg-type]
    assert not err.value.transient
    assert sheet.calls == ["read"] and sheet.row_for("a")[1] == "x"
    assert check_blocking(sheet).header == "mismatch"  # type: ignore[arg-type]


def test_check() -> None:
    assert check_blocking(FakeSheetClient()).header == "empty"  # type: ignore[arg-type]
    ok = FakeSheetClient([HEADERS])
    assert check_blocking(ok).header == "ok" and check_blocking(ok).reachable  # type: ignore[arg-type]
    down = FakeSheetClient([HEADERS])
    down.fail_with = SheetsError("busy", transient=True, status=503)
    assert not check_blocking(down).reachable  # type: ignore[arg-type]


# --- Error classification -----------------------------------------------------------------------


def _http_error(status: int, message: str = "nope") -> Exception:
    import json

    from googleapiclient.errors import HttpError

    resp = SimpleNamespace(status=status, reason="x")
    content = json.dumps({"error": {"message": message}}).encode()
    error: Exception = HttpError(resp, content)
    return error


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_temporary_http_errors_are_transient(status: int) -> None:
    assert classify(_http_error(status)).transient


@pytest.mark.parametrize("status", [400, 403, 404])
def test_config_errors_are_permanent(status: int) -> None:
    err = classify(_http_error(status), service_email="sa@x.iam.gserviceaccount.com")
    assert not err.transient and err.status == status
    if status == 403:
        assert "sa@x.iam.gserviceaccount.com" in err.message and "Editor" in err.message
    if status == 404:
        assert "GOOGLE_SHEET_ID" in err.message


def test_network_errors_are_transient() -> None:
    from google.auth.exceptions import RefreshError, TransportError

    assert classify(TimeoutError("timed out")).transient
    assert classify(ConnectionResetError()).transient
    assert classify(TransportError("dns")).transient  # type: ignore[no-untyped-call]
    assert not classify(RefreshError("invalid_grant")).transient  # type: ignore[no-untyped-call]


def test_missing_key_file_is_a_config_error(tmp_path: Any) -> None:
    from app.services.sheets_service import SheetsClient

    with pytest.raises(SheetsError) as err:
        SheetsClient(str(tmp_path / "missing.json"), "sheet-id", "Candidates")
    assert not err.value.transient and "not found" in err.value.message
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    with pytest.raises(SheetsError) as err:
        SheetsClient(str(bad), "sheet-id", "Candidates")
    assert not err.value.transient


def test_backoff_jitter_is_bounded() -> None:
    from datetime import timedelta

    from app.services.sync_service import jittered

    waits = {jittered(timedelta(minutes=10)) for _ in range(50)}
    assert all(timedelta(minutes=10) <= w <= timedelta(minutes=12) for w in waits)
    assert len(waits) > 1


def test_unreadable_key_file_is_a_config_error(tmp_path: Any) -> None:
    import os

    from app.services.sheets_service import SheetsClient

    key = tmp_path / "key.json"
    key.write_text("{}")
    os.chmod(key, 0)
    if os.access(key, os.R_OK):  # running as root: permissions don't apply
        pytest.skip("root can read anything")
    with pytest.raises(SheetsError) as err:
        SheetsClient(str(key), "sheet-id", "Candidates")
    assert not err.value.transient and "can't be read" in err.value.message
