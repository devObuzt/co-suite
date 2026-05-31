from bs4 import BeautifulSoup

from api.services.multi_scraper import _extract_heading_candidates, _extract_service_candidates


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
