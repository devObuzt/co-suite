from bs4 import BeautifulSoup

from api.services.brand_ai import _apply_source_fallbacks
from api.services.multi_scraper import (
    _extract_catalog_candidates,
    _extract_heading_candidates,
    _extract_service_candidates,
)


def test_extract_service_candidates_prioritizes_service_headings():
    html = """
    <main>
      <h2>השירותים שלנו</h2>
      <h3>חנות אינטרנטית</h3>
      <h3>שיווק דיגטלי</h3>
      <h3>SEO - קידום אורגני</h3>
      <h3>מיתוג וזהות עסקית</h3>
      <h3>אפליקציות לסמארטפונים</h3>
    </main>
    """
    soup = BeautifulSoup(html, "html.parser")
    headings = _extract_heading_candidates(soup)
    candidates = _extract_service_candidates(soup.get_text(" ", strip=True), headings)

    assert "שיווק דיגטלי" in candidates
    assert "SEO - קידום אורגני" in candidates
    assert "מיתוג וזהות עסקית" in candidates
    assert "אפליקציות לסמארטפונים" in candidates


def test_extract_service_candidates_handles_hebrew_ecommerce_catalog_links():
    html = """
    <main>
      <a href="/product-category/strollers">עגלות וטיולונים</a>
      <a href="/product-category/baby-feeding">האכלה והנקה</a>
      <a href="/product-category/car-seats">מושבי בטיחות</a>
      <a href="/product-category/toys">צעצועים</a>
      <a href="/product-category/baby-furniture">ריהוט לתינוקות</a>
      <a href="/cart">עגלת הקניות</a>
      <a href="/coupon">יש לך קוד קופון?</a>
    </main>
    """
    soup = BeautifulSoup(html, "html.parser")
    catalog = _extract_catalog_candidates(soup)
    candidates = _extract_service_candidates(soup.get_text(" ", strip=True), catalog)

    assert "עגלות וטיולונים" in candidates
    assert "האכלה והנקה" in candidates
    assert "מושבי בטיחות" in candidates
    assert "צעצועים" in candidates
    assert "ריהוט לתינוקות" in candidates
    assert "עגלת הקניות" not in candidates
    assert "יש לך קוד קופון?" not in candidates


def test_source_fallback_places_store_candidates_in_products():
    brand = {"research_debug": {"ai_output": {"services_count": 0, "products_count": 0}}}
    intel = {
        "sources": [
            {
                "type": "website",
                "title": "BSBEBE",
                "description": "חנות מוצרי תינוקות וצעצועים",
                "body_text": "קנה עכשיו עגלות וטיולונים צעצועים מוצרי בטיחות לתינוק ₪",
                "service_candidates": ["עגלות וטיולונים", "האכלה והנקה", "מושבי בטיחות"],
            }
        ]
    }

    result = _apply_source_fallbacks(brand, intel)

    assert result["products"] == ["עגלות וטיולונים", "האכלה והנקה", "מושבי בטיחות"]
    assert "services" not in result
    assert "products_from_source_candidates" in result["research_debug"]["fallbacks_applied"]
    assert result["research_debug"]["final_output"]["products_count"] == 3
