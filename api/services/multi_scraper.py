"""Multi-source business intelligence gatherer.

Accepts any mix of URLs (website, Instagram, Facebook, TikTok, LinkedIn, etc.)
and searches the web to build a rich brand intelligence package for Claude.
"""
import asyncio
import logging
import re
from typing import Optional
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ── URL classification ─────────────────────────────────────────────────────────

def classify_url(url: str) -> str:
    url = url.lower().strip()
    if not url.startswith("http"):
        url = "https://" + url
    host = urlparse(url).netloc
    if "instagram.com" in host:
        return "instagram"
    if "facebook.com" in host or "fb.com" in host:
        return "facebook"
    if "tiktok.com" in host:
        return "tiktok"
    if "linkedin.com" in host:
        return "linkedin"
    if "twitter.com" in host or "x.com" in host:
        return "twitter"
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    return "website"


def extract_handle(url: str, platform: str) -> Optional[str]:
    """Pull @username or page slug from a social URL."""
    path = urlparse(url).path.strip("/")
    parts = [p for p in path.split("/") if p]
    if parts:
        handle = parts[0].lstrip("@")
        return handle
    return None


# ── Website scraper ────────────────────────────────────────────────────────────

async def scrape_website(url: str) -> dict:
    """Extract text, meta tags, colors, logo, services from any website."""
    try:
        async with httpx.AsyncClient(
            headers=BROWSER_HEADERS, timeout=15,
            follow_redirects=True, verify=False,
        ) as client:
            resp = await client.get(url)
            html = resp.text
    except Exception as e:
        log.warning("Website fetch failed for %s: %s", url, e)
        return {"url": url, "error": str(e)}

    soup = BeautifulSoup(html, "html.parser")

    # Basic metadata
    title = soup.title.string.strip() if soup.title else ""
    desc = (
        _meta(soup, "description") or
        _meta(soup, "og:description") or
        _meta(soup, "twitter:description") or ""
    )
    og_title = _meta(soup, "og:title") or title
    og_image = _meta(soup, "og:image") or ""
    theme_color = _meta(soup, "theme-color") or _meta(soup, "msapplication-TileColor") or ""
    keywords = _meta(soup, "keywords") or ""

    # Logo candidates
    logo_urls = []
    for rel in ["icon", "shortcut icon", "apple-touch-icon", "apple-touch-icon-precomposed"]:
        tag = soup.find("link", rel=lambda r: r and rel in r)
        if tag and tag.get("href"):
            logo_urls.append(tag["href"])

    # JSON-LD structured data (goldmine for business info)
    jsonld_text = ""
    for tag in soup.find_all("script", type="application/ld+json"):
        jsonld_text += tag.string or ""

    # Extract colors from inline styles and CSS links
    colors = _extract_colors_from_html(html)
    if theme_color:
        colors.insert(0, theme_color)

    heading_candidates = _extract_heading_candidates(soup)
    catalog_candidates = _extract_catalog_candidates(soup)

    # Body text (strip nav/footer noise)
    for tag in soup(["nav", "footer", "script", "style", "header"]):
        tag.decompose()
    body_text = " ".join(soup.get_text(" ", strip=True).split())[:8000]
    service_candidates = _extract_service_candidates(
        body_text,
        [*heading_candidates, *catalog_candidates],
    )

    return {
        "type": "website",
        "url": url,
        "title": og_title or title,
        "description": desc,
        "og_image": og_image,
        "theme_color": theme_color,
        "colors": colors[:6],
        "logo_candidates": logo_urls[:3],
        "keywords": keywords,
        "jsonld": jsonld_text[:2000],
        "heading_candidates": heading_candidates[:30],
        "catalog_candidates": catalog_candidates[:30],
        "service_candidates": service_candidates,
        "body_text": body_text[:5000],
    }


def _meta(soup: BeautifulSoup, name: str) -> str:
    tag = (
        soup.find("meta", attrs={"name": name}) or
        soup.find("meta", attrs={"property": name}) or
        soup.find("meta", attrs={"itemprop": name})
    )
    return (tag.get("content") or "").strip() if tag else ""


def _extract_colors_from_html(html: str) -> list[str]:
    """Pull hex colors from CSS in the page."""
    found = re.findall(r"#([0-9a-fA-F]{6})\b", html)
    # Deduplicate, skip pure white/black/grey
    seen = set()
    colors = []
    for c in found:
        upper = c.upper()
        if upper in seen:
            continue
        seen.add(upper)
        # Skip near-white, near-black, pure greys
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        if max(r, g, b) < 30 or min(r, g, b) > 220:
            continue
        if abs(r - g) < 15 and abs(g - b) < 15:  # grey
            continue
        colors.append(f"#{upper}")
        if len(colors) >= 10:
            break
    return colors


def _extract_heading_candidates(soup: BeautifulSoup) -> list[str]:
    """Collect visible headings/card titles, which often carry service names."""
    selectors = [
        "h1", "h2", "h3", "h4",
        ".elementor-heading-title",
        ".elementor-image-box-title",
        ".elementor-icon-box-title",
    ]
    candidates: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        for node in soup.select(selector):
            clean = " ".join(node.get_text(" ", strip=True).split())
            if not clean or len(clean) < 3 or len(clean) > 90:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(clean)
    return candidates


def _extract_catalog_candidates(soup: BeautifulSoup) -> list[str]:
    """Collect product/category names from ecommerce menus and product grids."""
    link_hints = (
        "product", "product-category", "product_cat", "category", "shop", "catalog",
        "מוצר", "קטגור", "חנות", "עגלה", "עגלות", "טיולון", "תינוק", "צעצוע",
        "منتج", "تصنيف", "متجر", "عربة", "طفل", "ألعاب",
    )
    text_noise = {
        "ראשי", "אודותינו", "תקנון", "יצירת קשר", "בלוג", "עגלת הקניות",
        "רשימת משאלות", "חפש", "תפריט", "קנה עכשיו", "מבצע", "רגיל",
        "home", "about", "contact", "blog", "cart", "wishlist", "search",
        "الرئيسية", "من نحن", "تواصل", "السلة", "بحث", "اشتري الآن",
    }
    candidates: list[str] = []
    seen: set[str] = set()

    selectors = [
        "a",
        ".product-category",
        ".woocommerce-loop-category__title",
        ".woocommerce-loop-product__title",
        ".product-title",
        ".menu-item",
    ]
    for selector in selectors:
        for node in soup.select(selector):
            text = " ".join(node.get_text(" ", strip=True).split())
            href = str(node.get("href") or "")
            classes = " ".join(node.get("class") or [])
            haystack = f"{href} {classes} {text}".lower()
            if not any(hint.lower() in haystack for hint in link_hints):
                continue
            text = re.sub(r"\s*\(\d+\)\s*$", "", text)
            text = re.sub(r"\s+\d+(?:[,.]\d+)?\s*₪.*$", "", text)
            text = " ".join(text.strip(" -–—:|·*✅⭐").split())
            if len(text) < 3 or len(text) > 70:
                continue
            lower = text.lower()
            if (
                lower in text_noise
                or lower.startswith(("עגלת הקניות", "cart", "السلة"))
                or any(noise in lower for noise in ["₪", "coupon", "קופון"])
            ):
                continue
            if not re.search(r"[A-Za-z\u0590-\u05FF\u0600-\u06FF]", text):
                continue
            if lower in seen:
                continue
            seen.add(lower)
            candidates.append(text)
            if len(candidates) >= 30:
                return candidates
    return candidates


def _extract_service_candidates(text: str, heading_candidates: list[str] | None = None) -> list[str]:
    """Pull likely service/product phrases from headings and service-list copy."""
    if not text and not heading_candidates:
        return []

    anchors = [
        "our services", "services", "products", "solutions",
        "השירותים שלנו", "שירותים", "מוצרים", "פתרונות",
        "خدماتنا", "الخدمات", "منتجات", "حلول",
    ]
    lowered = text.lower()
    chunks: list[str] = []

    for anchor in anchors:
        idx = lowered.find(anchor.lower())
        if idx >= 0:
            chunks.append(text[idx:idx + 1800])

    chunks.append(text[:2500])
    candidate_text = " ".join(chunks)

    # Split on sentence-ish boundaries while preserving RTL phrases.
    parts = re.split(r"[•\n\r\t]|(?:\s{2,})|(?<=[.!?؟])\s+", candidate_text)
    candidates: list[str] = []
    seen: set[str] = set()
    noise = {
        "home", "about", "contact", "menu", "skip", "privacy",
        "cart", "coupon", "wishlist", "search", "buy now",
        "בית", "דלג", "תוכן", "צרו קשר", "רוצים לדעת עוד", "קופון", "עגלה", "קנה עכשיו",
        "الرئيسية", "تواصل", "المزيد", "السلة", "كوبون", "اشتري الآن",
    }

    heading_candidates = heading_candidates or []
    offering_words = (
        "service", "marketing", "branding", "seo", "website", "app", "content", "campaign", "ecommerce",
        "baby", "stroller", "feeding", "nursing", "car seat", "toy", "furniture", "garden",
        "שיווק", "מיתוג", "פיתוח", "אתר", "אפליק", "קידום", "פרסום", "תוכן", "קמפיינים", "חנות", "אוטומציה",
        "תינוק", "עגלה", "עגלות", "טיולון", "האכלה", "הנקה", "בטיחות", "סלקל", "כיסא", "צעצוע", "ריהוט", "גן",
        "تسويق", "براند", "تطوير", "موقع", "تطبيق", "محتوى", "حملات", "تصميم", "متجر", "أتمتة",
        "أطفال", "طفل", "عربة", "رضاعة", "ألعاب", "كرسي", "أمان", "أثاث",
    )

    for heading in heading_candidates:
        lower = heading.lower()
        if lower in noise or lower.startswith(("עגלת הקניות", "cart", "السلة")):
            continue
        if any(w in lower for w in offering_words):
            seen.add(lower)
            candidates.append(heading)

    for part in parts:
        clean = " ".join(part.strip(" -–—:|·*✅⭐").split())
        if not clean or len(clean) < 4 or len(clean) > 90:
            continue
        lower = clean.lower()
        if any(n in lower for n in noise):
            continue
        if not re.search(r"[A-Za-z\u0590-\u05FF\u0600-\u06FF]", clean):
            continue
        # Prefer phrases that look like offerings, but keep enough fallback text.
        if not any(w in lower for w in offering_words) and len(candidates) >= 6:
            continue
        key = lower
        if key in seen:
            continue
        seen.add(key)
        candidates.append(clean)
        if len(candidates) >= 18:
            break

    return candidates


# ── Social media scraper ──────────────────────────────────────────────────────

# Instagram mobile app headers — lets us call the unofficial profile API
IG_HEADERS = {
    "User-Agent": (
        "Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2400; "
        "samsung; SM-G991B; o1s; exynos2100; en_US; 458229258)"
    ),
    "X-IG-App-ID": "936619743392459",
    "Accept-Language": "en-US",
    "Accept": "*/*",
}


async def scrape_instagram(url: str) -> dict:
    """
    Extract profile info + recent posts from a public Instagram account.

    Strategy:
    1. Try unofficial IG API (web_profile_info) → full profile + posts JSON
    2. Fall back to og: meta tags on the public profile page
    """
    handle = extract_handle(url, "instagram") or url
    result: dict = {"type": "instagram", "handle": handle, "url": url}

    # ── Attempt 1: unofficial JSON API ───────────────────────────────────────
    try:
        api_url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={handle}"
        async with httpx.AsyncClient(headers=IG_HEADERS, timeout=15, follow_redirects=True) as client:
            resp = await client.get(api_url)

        if resp.status_code == 200:
            data = resp.json()
            user = data.get("data", {}).get("user", {})

            result["full_name"] = user.get("full_name", "")
            result["bio"] = user.get("biography", "").replace("\n", " ")
            result["followers"] = user.get("edge_followed_by", {}).get("count", 0)
            result["following"] = user.get("edge_follow", {}).get("count", 0)
            result["posts_count"] = user.get("edge_owner_to_timeline_media", {}).get("count", 0)
            result["website"] = user.get("external_url", "")
            result["is_business"] = user.get("is_business_account", False)
            result["business_category"] = user.get("business_category_name", "")
            result["business_email"] = user.get("business_email", "")
            result["business_phone"] = user.get("business_phone_number", "")
            result["profile_pic"] = user.get("profile_pic_url_hd") or user.get("profile_pic_url", "")

            # Extract recent posts
            edges = user.get("edge_owner_to_timeline_media", {}).get("edges", [])
            posts = []
            all_hashtags: dict[str, int] = {}

            for edge in edges[:12]:
                node = edge.get("node", {})
                caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
                caption = caption_edges[0]["node"]["text"] if caption_edges else ""

                # Extract hashtags from caption
                tags = re.findall(r"#(\w+)", caption)
                for tag in tags:
                    all_hashtags[tag.lower()] = all_hashtags.get(tag.lower(), 0) + 1

                posts.append({
                    "type": node.get("__typename", "GraphImage"),
                    "likes": node.get("edge_liked_by", {}).get("count", 0),
                    "comments": node.get("edge_media_to_comment", {}).get("count", 0),
                    "caption": caption[:300],
                    "timestamp": node.get("taken_at_timestamp"),
                    "thumbnail": node.get("thumbnail_src") or node.get("display_url", ""),
                })

            result["recent_posts"] = posts
            # Top hashtags sorted by frequency
            result["top_hashtags"] = sorted(all_hashtags, key=lambda k: -all_hashtags[k])[:20]
            # Aggregate captions for Claude context
            result["captions_sample"] = "\n---\n".join(
                p["caption"] for p in posts if p["caption"]
            )[:3000]

            log.info("IG API success for @%s: %d posts, %d followers", handle,
                     len(posts), result["followers"])
            return result

    except Exception as e:
        log.warning("IG unofficial API failed for @%s: %s", handle, e)

    # ── Attempt 2: og: meta tags from public profile page ────────────────────
    try:
        async with httpx.AsyncClient(headers=BROWSER_HEADERS, timeout=12, follow_redirects=True) as client:
            resp = await client.get(f"https://www.instagram.com/{handle}/")
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        result["og_title"] = _meta(soup, "og:title")
        result["og_description"] = _meta(soup, "og:description")
        result["og_image"] = _meta(soup, "og:image")

        for pattern, key in [
            (r'"biography":"(.*?)"', "bio"),
            (r'"full_name":"(.*?)"', "full_name"),
            (r'"external_url":"(.*?)"', "website"),
        ]:
            m = re.search(pattern, html)
            if m:
                result[key] = m.group(1).replace("\\n", " ").replace("\\/", "/")
        m = re.search(r'"edge_followed_by":\{"count":(\d+)\}', html)
        if m:
            result["followers"] = int(m.group(1))
    except Exception as e:
        log.warning("IG profile page fallback failed for @%s: %s", handle, e)

    return result


async def scrape_facebook(url: str) -> dict:
    """Extract basic info from a Facebook page."""
    handle = extract_handle(url, "facebook") or url
    result = {"type": "facebook", "handle": handle, "url": url}
    try:
        async with httpx.AsyncClient(headers=BROWSER_HEADERS, timeout=12, follow_redirects=True) as client:
            resp = await client.get(url)
            html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        result["og_title"] = _meta(soup, "og:title")
        result["og_description"] = _meta(soup, "og:description")
        result["og_image"] = _meta(soup, "og:image")
        body = soup.get_text(" ", strip=True)[:2000]
        result["text"] = body
    except Exception as e:
        log.warning("Facebook scrape failed: %s", e)
    return result


async def scrape_linkedin(url: str) -> dict:
    """Extract visible LinkedIn page info."""
    result = {"type": "linkedin", "url": url}
    try:
        async with httpx.AsyncClient(headers=BROWSER_HEADERS, timeout=12, follow_redirects=True) as client:
            resp = await client.get(url)
            html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        result["og_title"] = _meta(soup, "og:title")
        result["og_description"] = _meta(soup, "og:description")
        result["og_image"] = _meta(soup, "og:image")
    except Exception as e:
        log.warning("LinkedIn scrape failed: %s", e)
    return result


# ── Web search ────────────────────────────────────────────────────────────────

async def search_business(business_name: str, location: str = "") -> str:
    """Search DuckDuckGo for business info. Returns text snippets."""
    query = business_name
    if location:
        query += f" {location}"

    snippets = []

    # DuckDuckGo HTML search (no API key needed)
    try:
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        async with httpx.AsyncClient(headers=BROWSER_HEADERS, timeout=12) as client:
            resp = await client.get(search_url)
            soup = BeautifulSoup(resp.text, "html.parser")

        for result in soup.select(".result__snippet")[:5]:
            text = result.get_text(" ", strip=True)
            if text:
                snippets.append(text)
    except Exception as e:
        log.warning("DuckDuckGo search failed: %s", e)

    # Also try Google
    if len(snippets) < 2:
        try:
            g_url = f"https://www.google.com/search?q={quote_plus(query)}&hl=en&num=5"
            async with httpx.AsyncClient(headers={**BROWSER_HEADERS, "Accept-Language": "en-US"}, timeout=12) as client:
                resp = await client.get(g_url)
                soup = BeautifulSoup(resp.text, "html.parser")
            for span in soup.select("[data-sncf], .VwiC3b, .yXK7lf")[:5]:
                text = span.get_text(" ", strip=True)
                if text and len(text) > 30:
                    snippets.append(text)
        except Exception as e:
            log.warning("Google search failed: %s", e)

    return "\n".join(snippets[:6])


def classify_platform(url: str) -> str:
    u = str(url or "").lower()
    if "instagram.com" in u:
        return "instagram"
    if "tiktok.com" in u:
        return "tiktok"
    if "facebook.com" in u or "fb.com" in u:
        return "facebook"
    return "web"


async def search_web(query: str, limit: int = 6) -> list[dict]:
    """Free web search (DuckDuckGo HTML with Google HTML fallback).

    Returns [{title, url, snippet, platform}] — the engine behind the dashboard
    market-research section, reused by marketing-plan competitor research.
    """
    items: list[dict] = []
    try:
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        async with httpx.AsyncClient(headers=BROWSER_HEADERS, timeout=12) as client:
            resp = await client.get(search_url)
        soup = BeautifulSoup(resp.text, "html.parser")
        # DDG HTML structure: results are .result, title link is .result__a,
        # snippet is .result__snippet. The href may be a DDG redirect — extract
        # the real URL from the uddg param when present.
        for el in soup.select(".result")[:limit]:
            title_el = el.select_one("a.result__a")
            snippet_el = el.select_one(".result__snippet")
            if not title_el:
                continue
            raw_href = title_el.get("href", "") or ""
            # Extract real URL from DDG redirect (e.g. /l/?uddg=https%3A%2F%2F...)
            if "uddg=" in raw_href:
                from urllib.parse import parse_qs, urlparse, unquote
                qs = parse_qs(urlparse(raw_href).query)
                url = unquote(qs.get("uddg", [""])[0])
            else:
                url = raw_href
            title = title_el.get_text(strip=True)
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            if url and title and url.startswith("http"):
                items.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "platform": classify_platform(url),
                })
    except Exception as e:
        log.warning("Market search failed for '%s': %s", query, e)
    # Fallback to Google if DDG returned nothing
    if not items:
        try:
            g_url = f"https://www.google.com/search?q={quote_plus(query)}&hl=en&num={limit}"
            async with httpx.AsyncClient(headers={**BROWSER_HEADERS, "Accept-Language": "en-US"}, timeout=12) as client:
                resp = await client.get(g_url)
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.select("a[href]")[:20]:
                href = a.get("href", "")
                if href.startswith("/url?q="):
                    real = href[7:].split("&")[0]
                    from urllib.parse import unquote as _uq
                    real = _uq(real)
                    if real.startswith("http") and "google.com" not in real:
                        title = a.get_text(strip=True)
                        if title and len(title) > 5:
                            items.append({
                                "title": title,
                                "url": real,
                                "snippet": "",
                                "platform": classify_platform(real),
                            })
                    if len(items) >= limit - 1:
                        break
        except Exception as e2:
            log.warning("Google fallback failed for '%s': %s", query, e2)
    return items


async def search_market_content(keyword: str, location: str, strategy: dict) -> list[dict]:
    """Search for competitor content and trending social posts in the market."""
    results = []
    _search = search_web

    # Search for Instagram content in the niche + location
    if keyword:
        q1 = f"site:instagram.com {keyword} {location}".strip()
        results.extend(await _search(q1))

    # Search for known competitors from strategy
    competitors = (strategy.get("marketing_plan") or {}).get("competitors") or []
    for comp in competitors[:3]:
        name = comp.get("name", "")
        if name:
            results.extend(await _search(f"{name} instagram {location}".strip()))

    # General social content search in the market
    if keyword and location:
        q3 = f"instagram tiktok {keyword} {location} trending"
        results.extend(await _search(q3))

    # Deduplicate by URL and cap at 10
    seen: set[str] = set()
    unique = []
    for r in results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)
        if len(unique) >= 10:
            break

    return unique


# ── Main aggregator ────────────────────────────────────────────────────────────

async def gather_all_sources(
    urls: list[str],
    business_name: Optional[str] = None,
) -> dict:
    """
    Given a list of URLs (any mix of website/social), gather all available
    business intelligence concurrently. Returns a structured dict for Claude.
    """
    tasks = []
    metadata = []

    for url in urls:
        if not url.strip():
            continue
        url = url.strip()
        if not url.startswith("http"):
            url = "https://" + url
        kind = classify_url(url)
        metadata.append((kind, url))

        if kind == "instagram":
            tasks.append(scrape_instagram(url))
        elif kind == "facebook":
            tasks.append(scrape_facebook(url))
        elif kind == "linkedin":
            tasks.append(scrape_linkedin(url))
        else:
            tasks.append(scrape_website(url))

    # Fire all scrapes in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)
    sources = []
    source_reports = []
    for (kind, url), r in zip(metadata, results):
        if isinstance(r, Exception):
            error = str(r)
            log.warning("Scrape failed for %s (%s): %s", url, kind, error)
            source_reports.append({
                "url": url,
                "kind": kind,
                "status": "failed",
                "error": error,
                "text_chars": 0,
                "service_candidates": 0,
                "recent_posts": 0,
                "captions_chars": 0,
            })
        else:
            sources.append(r)
            error = r.get("error")
            body_text = r.get("body_text") or r.get("text") or ""
            captions = r.get("captions_sample") or ""
            report = {
                "url": url,
                "kind": r.get("type") or kind,
                "status": "failed" if error else "ok",
                "error": error or "",
                "title": r.get("title") or r.get("og_title") or r.get("full_name") or r.get("handle") or "",
                "text_chars": len(body_text),
                "description_chars": len(r.get("description") or r.get("og_description") or r.get("bio") or ""),
                "service_candidates": len(r.get("service_candidates") or []),
                "recent_posts": len(r.get("recent_posts") or []),
                "captions_chars": len(captions),
            }
            if not error and not any([
                report["title"],
                report["text_chars"],
                report["description_chars"],
                report["service_candidates"],
                report["recent_posts"],
                report["captions_chars"],
            ]):
                report["status"] = "empty"
            source_reports.append(report)

    # Web search for extra intel
    search_snippets = ""
    if business_name and business_name.strip():
        search_snippets = await search_business(business_name)
    elif sources:
        # Try to infer name from first source
        first = sources[0]
        inferred_name = (
            first.get("title") or first.get("og_title") or
            first.get("full_name") or first.get("handle") or ""
        )
        if inferred_name:
            search_snippets = await search_business(inferred_name)

    return {
        "sources": sources,
        "search_snippets": search_snippets,
        "business_name_hint": business_name or "",
        "debug": {
            "source_reports": source_reports,
            "sources_requested": len(metadata),
            "sources_ok": sum(1 for item in source_reports if item.get("status") == "ok"),
            "sources_failed": sum(1 for item in source_reports if item.get("status") == "failed"),
            "sources_empty": sum(1 for item in source_reports if item.get("status") == "empty"),
            "search_snippets_chars": len(search_snippets or ""),
        },
    }
