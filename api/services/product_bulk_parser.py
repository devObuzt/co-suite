from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from zipfile import ZipFile

from openpyxl import load_workbook


DEFAULT_HEBREW_MAPPING = {
    "שם": "product_name",
    "תמונה": "image_ref",
    "סלוגן": "slogan",
    "תיאור המוצר": "description",
    "מחיר לסט שלם + מע\"מ": "price",
    "תוספת בכל העיצובים": "global_addition",
    "הערות": "notes",
}

IMAGE_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@dataclass
class ParsedWorkbook:
    headers: list[str]
    mapping: dict[str, str]
    rows: list[dict[str, Any]]


@dataclass
class ZipImage:
    filename: str
    data: bytes
    content_type: str


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_filename(value: str) -> str:
    cleaned = clean_cell(value).replace("\\", "/")
    return PurePosixPath(cleaned).name.strip().lower()


def detect_column_mapping(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for header in headers:
        target = DEFAULT_HEBREW_MAPPING.get(clean_cell(header))
        if target:
            mapping[target] = header
    return mapping


def parse_workbook(xlsx_bytes: bytes, mapping: dict[str, str] | None = None) -> ParsedWorkbook:
    wb = load_workbook(BytesIO(xlsx_bytes), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))

    header_row_index = None
    header_row = None
    for idx, row in enumerate(rows):
        if any(clean_cell(cell) for cell in row):
            header_row_index = idx
            header_row = row
            break

    if header_row_index is None or header_row is None:
        return ParsedWorkbook(headers=[], mapping={}, rows=[])

    headers = [clean_cell(cell) for cell in header_row]
    active_mapping = mapping or detect_column_mapping(headers)
    header_index = {header: idx for idx, header in enumerate(headers)}
    data_rows: list[dict[str, Any]] = []

    for row_index, row in enumerate(rows[header_row_index + 1 :], start=header_row_index + 2):
        raw_row = {
            header: clean_cell(row[idx] if idx < len(row) else "")
            for header, idx in header_index.items()
        }
        if not any(raw_row.values()):
            continue

        normalized: dict[str, Any] = {"row_index": row_index, "raw_row": raw_row}
        for field, header in active_mapping.items():
            normalized[field] = raw_row.get(header, "")
        normalized.setdefault("product_name", "")
        normalized.setdefault("image_ref", "")
        data_rows.append(normalized)

    return ParsedWorkbook(headers=headers, mapping=active_mapping, rows=data_rows)


def match_zip_images(zip_bytes: bytes, image_refs: list[str]) -> dict[str, ZipImage]:
    wanted = {normalize_filename(ref): ref for ref in image_refs if clean_cell(ref)}
    matches: dict[str, ZipImage] = {}

    with ZipFile(BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            suffix = PurePosixPath(info.filename).suffix.lower()
            if info.is_dir() or suffix not in IMAGE_CONTENT_TYPES:
                continue

            original_ref = wanted.get(normalize_filename(info.filename))
            if original_ref and original_ref not in matches:
                matches[original_ref] = ZipImage(
                    filename=info.filename,
                    data=zf.read(info),
                    content_type=IMAGE_CONTENT_TYPES[suffix],
                )

    return matches
