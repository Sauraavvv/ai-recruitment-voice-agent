"""Read uploaded candidate files (.csv / .xlsx) into header + rows of plain text cells.

Pure functions: callers run `parse_upload` in a thread (`asyncio.to_thread`) so parsing never
blocks the event loop.
"""

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import PurePath

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_DATA_ROWS = 1000
ALLOWED_EXTENSIONS = (".csv", ".xlsx")
XLSX_SIGNATURE = b"PK\x03\x04"


class FileParseError(ValueError):
    """The file can't be read at all. `code` is stable; `message` is shown to the recruiter."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ParsedFile:
    headers: list[str]
    rows: list[list[str]]  # each row padded/truncated to len(headers)
    # 1-based spreadsheet row number of each data row, for error messages.
    row_numbers: list[int]


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        # Excel stores phone numbers as numbers: 9876543210.0 -> "9876543210".
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def clean_cell(value: str) -> str:
    text = value.strip()
    if text.startswith("'"):  # Excel text-prefix
        text = text[1:].strip()
    return text


def _table_from_rows(raw_rows: list[list[str]]) -> ParsedFile:
    header_index = None
    for index, row in enumerate(raw_rows):
        if any(clean_cell(cell) for cell in row):
            header_index = index
            break
    if header_index is None:
        raise FileParseError("empty_file", "The file has no data")

    headers = [clean_cell(cell) for cell in raw_rows[header_index]]
    while headers and not headers[-1]:
        headers.pop()
    if not headers:
        raise FileParseError("empty_file", "The file has no header row")

    rows: list[list[str]] = []
    row_numbers: list[int] = []
    for offset, raw in enumerate(raw_rows[header_index + 1 :], start=header_index + 2):
        cells = [clean_cell(cell) for cell in raw[: len(headers)]]
        cells += [""] * (len(headers) - len(cells))
        if not any(cells):
            continue
        if len(rows) >= MAX_DATA_ROWS:
            raise FileParseError(
                "too_many_rows", f"The file has more than {MAX_DATA_ROWS} data rows; split it"
            )
        rows.append(cells)
        row_numbers.append(offset)
    if not rows:
        raise FileParseError("no_rows", "The file has a header row but no candidate rows")
    return ParsedFile(headers, rows, row_numbers)


def _read_csv(content: bytes) -> list[list[str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252", errors="replace")
    sample = text[:8192]
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [list(row) for row in csv.reader(io.StringIO(text), dialect)]


def _read_xlsx(content: bytes) -> list[list[str]]:
    from openpyxl import load_workbook  # imported lazily: only needed for Excel uploads

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise FileParseError("unreadable_file", "The Excel file could not be read") from exc
    try:
        sheet = workbook.worksheets[0]
        rows: list[list[str]] = []
        for row in sheet.iter_rows(values_only=True):
            rows.append([_cell_text(value) for value in row])
            # Stop early on absurd sheets; the exact row limit is applied after skipping blanks.
            if len(rows) > MAX_DATA_ROWS * 3:
                break
        return rows
    finally:
        workbook.close()


def parse_upload(filename: str, content: bytes) -> ParsedFile:
    extension = PurePath(filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise FileParseError(
            "unsupported_file_type",
            "Only .csv and .xlsx files are supported. "
            "For .xls or other Excel formats, save the file as .xlsx first.",
        )
    if len(content) > MAX_FILE_BYTES:
        raise FileParseError("file_too_large", "The file is larger than 5 MB")
    if not content:
        raise FileParseError("empty_file", "The file is empty")

    if extension == ".xlsx":
        if not content.startswith(XLSX_SIGNATURE):
            raise FileParseError("invalid_file_content", "The file is not a valid .xlsx workbook")
        raw_rows = _read_xlsx(content)
    else:
        if content.startswith((XLSX_SIGNATURE, b"%PDF", b"\xd0\xcf\x11\xe0")):
            raise FileParseError(
                "invalid_file_content", "The file has a .csv name but isn't a text CSV file"
            )
        raw_rows = _read_csv(content)
    return _table_from_rows(raw_rows)
