"""Real Google Sheets API against a dedicated TEST spreadsheet (phase-07 §7, marker `sheets`).

Needs GOOGLE_SERVICE_ACCOUNT_JSON (path to the key) and GOOGLE_TEST_SHEET_ID (a spreadsheet
shared with the service account, NOT the team's sheet). Each run works in a new tab and deletes
it afterwards. Run with `make test-sheets`.
"""

import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from app.services.sheet_mapping import HEADERS
from app.services.sheets_service import (
    HeaderMismatchError,
    SheetsClient,
    SheetsError,
    check_blocking,
    upsert_blocking,
)

pytestmark = pytest.mark.sheets

KEY = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
SHEET = os.getenv("GOOGLE_TEST_SHEET_ID")


@pytest.fixture
def client() -> Iterator[SheetsClient]:
    if not (KEY and SHEET):
        pytest.skip("GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_TEST_SHEET_ID are not set")
    c = SheetsClient(KEY, SHEET, f"test-{uuid.uuid4().hex[:8]}")
    yield c
    gid = c._sheet_gid()
    if gid is not None:
        c._run(
            c._sheets.spreadsheets().batchUpdate(
                spreadsheetId=SHEET, body={"requests": [{"deleteSheet": {"sheetId": gid}}]}
            )
        )


def read_all(c: SheetsClient, render: str = "UNFORMATTED_VALUE") -> list[list[Any]]:
    body = c._run(
        c._sheets.spreadsheets()
        .values()
        .get(spreadsheetId=SHEET, range=c._range("A1:W"), valueRenderOption=render)
    )
    return list(body.get("values", []))


def row(cid: str, name: str, **extra: Any) -> list[Any]:
    cells: list[Any] = [cid, name, "+919000000000", *[""] * 20]
    for index, value in extra.items():
        cells[int(index.removeprefix("c"))] = value
    return cells


def test_append_then_update_the_same_row(client: SheetsClient) -> None:
    assert check_blocking(client).header == "empty"  # the new tab was created
    first = upsert_blocking(client, {"a": row("a", "Asha"), "b": row("b", "Ravi")})
    assert first.appended == ["a", "b"]
    values = read_all(client)
    assert values[0] == HEADERS and [r[0] for r in values[1:]] == ["a", "b"]
    assert values[1][2] == "+919000000000"  # RAW: the + is kept

    second = upsert_blocking(client, {"a": row("a", "Asha Rao")})
    assert second.updated == ["a"] and second.appended == []
    values = read_all(client)
    assert len(values) == 3 and values[1][1] == "Asha Rao"


def test_manual_sort_then_update(client: SheetsClient) -> None:
    upsert_blocking(client, {c: row(c, n) for c, n in (("a", "Zed"), ("b", "Amy"), ("c", "Kim"))})
    gid = client._sheet_gid()
    client._run(
        client._sheets.spreadsheets().batchUpdate(
            spreadsheetId=SHEET,
            body={
                "requests": [
                    {
                        "sortRange": {
                            "range": {"sheetId": gid, "startRowIndex": 1},
                            "sortSpecs": [{"dimensionIndex": 1, "sortOrder": "ASCENDING"}],
                        }
                    }
                ]
            },
        )
    )
    assert [r[1] for r in read_all(client)[1:]] == ["Amy", "Kim", "Zed"]
    upsert_blocking(client, {"a": row("a", "Zed Updated")})
    values = read_all(client)
    assert [r[0] for r in values[1:]] == ["b", "c", "a"]
    assert values[3][1] == "Zed Updated"


def test_five_syncs_one_row_and_formulas_stay_text(client: SheetsClient) -> None:
    formula = '=HYPERLINK("http://example.com","x")'
    for i in range(5):
        upsert_blocking(client, {"a": row("a", f"v{i}", c6=formula, c9=12.5)})
    values = read_all(client, render="FORMULA")
    assert len(values) == 2
    assert values[1][6] == formula  # stored as text, not a formula (RAW)
    assert values[1][9] == 12.5  # numbers stay numbers


def test_header_changed_by_hand_blocks_writes(client: SheetsClient) -> None:
    upsert_blocking(client, {"a": row("a", "Asha")})
    client._run(
        client._sheets.spreadsheets()
        .values()
        .update(
            spreadsheetId=SHEET,
            range=client._range("B1"),
            valueInputOption="RAW",
            body={"values": [["Name"]]},
        )
    )
    with pytest.raises(HeaderMismatchError):
        upsert_blocking(client, {"a": row("a", "changed")})
    assert read_all(client)[1][1] == "Asha"


def test_wrong_spreadsheet_is_a_permanent_error() -> None:
    if not KEY:
        pytest.skip("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
    c = SheetsClient(KEY, "1" + "x" * 43, "Candidates")
    with pytest.raises(SheetsError) as err:
        upsert_blocking(c, {"a": row("a", "x")})
    assert not err.value.transient and err.value.status in (403, 404)
