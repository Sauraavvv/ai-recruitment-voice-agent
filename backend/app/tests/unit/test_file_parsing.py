from pathlib import Path

import pytest

from app.utils import file_parsing
from app.utils.file_parsing import FileParseError, parse_upload

FIXTURES = Path(__file__).parent.parent / "fixtures" / "imports"


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_csv_reads_header_and_rows() -> None:
    parsed = parse_upload("valid_5.csv", load("valid_5.csv"))
    assert parsed.headers[:3] == ["Candidate Name", "Phone Number", "Job Role"]
    assert len(parsed.rows) == 5
    assert parsed.row_numbers == [2, 3, 4, 5, 6]


def test_xlsx_numbers_become_digit_strings() -> None:
    parsed = parse_upload("numeric_phones.xlsx", load("numeric_phones.xlsx"))
    assert [r[1] for r in parsed.rows] == ["9000000201", "9000000202", "919000000203"]
    assert parsed.rows[0][4] == "4"


def test_cp1252_fallback() -> None:
    parsed = parse_upload("cp1252.csv", load("cp1252.csv"))
    assert parsed.rows[0][0] == "Test José Müller"


def test_semicolon_delimiter_detected() -> None:
    parsed = parse_upload("semicolon.csv", load("semicolon.csv"))
    assert parsed.headers == ["Name", "Mobile No", "Designation", "Email ID", "Exp"]
    assert parsed.rows[1] == ["Test Semi 02", "9000000502", "Analyst", "", "7 yrs"]


def test_header_is_first_non_empty_row_and_blank_rows_skipped() -> None:
    content = b"\n,,\nName,Phone,Role\n\nA,'9000000001,Dev\n,,\n"
    parsed = parse_upload("x.csv", content)
    assert parsed.headers == ["Name", "Phone", "Role"]
    assert parsed.rows == [["A", "9000000001", "Dev"]]
    assert parsed.row_numbers == [5]


@pytest.mark.parametrize(
    ("filename", "content", "code"),
    [
        ("wrong_type.pdf", load("wrong_type.pdf"), "unsupported_file_type"),
        ("old.xls", b"\xd0\xcf\x11\xe0rest", "unsupported_file_type"),
        ("macro.xlsm", b"PK\x03\x04rest", "unsupported_file_type"),
        ("fake.xlsx", b"Name,Phone\nA,1\n", "invalid_file_content"),
        ("renamed.csv", load("wrong_type.pdf"), "invalid_file_content"),
        ("empty.csv", b"", "empty_file"),
        ("header_only.csv", b"Name,Phone,Role\n", "no_rows"),
        ("broken.xlsx", b"PK\x03\x04not really a zip", "unreadable_file"),
    ],
)
def test_rejected_files(filename: str, content: bytes, code: str) -> None:
    with pytest.raises(FileParseError) as info:
        parse_upload(filename, content)
    assert info.value.code == code


def test_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_parsing, "MAX_FILE_BYTES", 10)
    with pytest.raises(FileParseError) as info:
        parse_upload("big.csv", b"Name,Phone,Role\nA,1,B\n")
    assert info.value.code == "file_too_large"


def test_row_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_parsing, "MAX_DATA_ROWS", 2)
    with pytest.raises(FileParseError) as info:
        parse_upload("many.csv", b"Name\nA\nB\nC\n")
    assert info.value.code == "too_many_rows"
