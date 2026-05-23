from io import BytesIO
from zipfile import ZipFile

from openpyxl import Workbook

from api.services.product_bulk_parser import (
    DEFAULT_HEBREW_MAPPING,
    detect_column_mapping,
    match_zip_images,
    parse_workbook,
)


def make_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["שם", "תמונה", "סלוגן", "תיאור המוצר", "מחיר לסט שלם + מע\"מ", "תוספת בכל העיצובים", "הערות"])
    ws.append(["שולחן עבודה", "desk 01.jpg", "עובדים נכון", "שולחן למשרד ביתי", "1290", "להוסיף לוגו", "צבע עץ"])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def make_zip() -> bytes:
    out = BytesIO()
    with ZipFile(out, "w") as zf:
        zf.writestr("products/desk 01.jpg", b"fake-image")
        zf.writestr("ignore/readme.txt", b"not image")
    return out.getvalue()


def test_detect_column_mapping_supports_hebrew_headers():
    headers = ["שם", "תמונה", "סלוגן", "תיאור המוצר", "מחיר לסט שלם + מע\"מ", "תוספת בכל העיצובים", "הערות"]

    mapping = detect_column_mapping(headers)

    assert mapping["product_name"] == "שם"
    assert mapping["image_ref"] == "תמונה"
    assert mapping["slogan"] == "סלוגן"
    assert mapping["description"] == "תיאור המוצר"
    assert mapping["price"] == "מחיר לסט שלם + מע\"מ"
    assert mapping["global_addition"] == "תוספת בכל העיצובים"
    assert mapping["notes"] == "הערות"
    assert DEFAULT_HEBREW_MAPPING["שם"] == "product_name"


def test_parse_workbook_returns_normalized_products():
    parsed = parse_workbook(make_xlsx())

    assert parsed.headers[0] == "שם"
    assert parsed.mapping["product_name"] == "שם"
    assert len(parsed.rows) == 1
    row = parsed.rows[0]
    assert row["product_name"] == "שולחן עבודה"
    assert row["image_ref"] == "desk 01.jpg"
    assert row["price"] == "1290"
    assert row["raw_row"]["הערות"] == "צבע עץ"


def test_match_zip_images_matches_by_basename_and_ignores_non_images():
    matches = match_zip_images(make_zip(), ["desk 01.jpg", "missing.jpg"])

    assert "desk 01.jpg" in matches
    assert matches["desk 01.jpg"].filename == "products/desk 01.jpg"
    assert matches["desk 01.jpg"].content_type == "image/jpeg"
    assert "missing.jpg" not in matches
