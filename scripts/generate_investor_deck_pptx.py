"""Generate the co-Suite investor deck as an editable PPTX using stdlib only."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import html


OUT = Path("docs/investor/co-suite-investor-deck.pptx")

SLIDE_W = 12192000
SLIDE_H = 6858000


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def emu(inches: float) -> int:
    return int(inches * 914400)


def rgb(hex_color: str) -> str:
    return hex_color.replace("#", "").upper()


def run(text: str, size: int = 2200, color: str = "F7F7F2", bold: bool = False) -> str:
    b = ' b="1"' if bold else ""
    return (
        f'<a:r><a:rPr lang="en-US" sz="{size}"{b}>'
        f'<a:solidFill><a:srgbClr val="{rgb(color)}"/></a:solidFill>'
        "</a:rPr>"
        f"<a:t>{esc(text)}</a:t></a:r>"
    )


def para(text: str, size: int = 2200, color: str = "F7F7F2", bold: bool = False, bullet: bool = False) -> str:
    bullet_xml = '<a:buChar char="•"/><a:buFont typeface="Arial"/>' if bullet else ""
    mar = ' marL="285750" indent="-171450"' if bullet else ""
    return f"<a:p><a:pPr{mar}>{bullet_xml}</a:pPr>{run(text, size, color, bold)}</a:p>"


def text_box(
    x: float,
    y: float,
    w: float,
    h: float,
    paragraphs: list[str],
    *,
    fill: str | None = None,
    line: str | None = None,
    radius: bool = False,
) -> str:
    shape = "roundRect" if radius else "rect"
    fill_xml = (
        f'<a:solidFill><a:srgbClr val="{rgb(fill)}"/></a:solidFill>'
        if fill
        else "<a:noFill/>"
    )
    line_xml = (
        f'<a:ln w="12700"><a:solidFill><a:srgbClr val="{rgb(line)}"/></a:solidFill></a:ln>'
        if line
        else "<a:ln><a:noFill/></a:ln>"
    )
    return f"""
    <p:sp>
      <p:nvSpPr><p:cNvPr id="{text_box.next_id()}" name="TextBox"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
      <p:spPr>
        <a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>
        <a:prstGeom prst="{shape}"><a:avLst/></a:prstGeom>
        {fill_xml}{line_xml}
      </p:spPr>
      <p:txBody>
        <a:bodyPr wrap="square" lIns="91440" tIns="91440" rIns="91440" bIns="91440"/>
        <a:lstStyle/>
        {''.join(paragraphs)}
      </p:txBody>
    </p:sp>
    """


def _next_id() -> int:
    _next_id.value += 1
    return _next_id.value


_next_id.value = 1
text_box.next_id = _next_id  # type: ignore[attr-defined]


def rect(x: float, y: float, w: float, h: float, color: str) -> str:
    return f"""
    <p:sp>
      <p:nvSpPr><p:cNvPr id="{text_box.next_id()}" name="Accent"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
      <p:spPr>
        <a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>
        <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        <a:solidFill><a:srgbClr val="{rgb(color)}"/></a:solidFill><a:ln><a:noFill/></a:ln>
      </p:spPr>
    </p:sp>
    """


def card(x: float, y: float, w: float, h: float, title: str, body: str, dark: bool = True, accent: str = "D7FF21") -> str:
    bg = "1A1A1E" if dark else "F1F0EA"
    border = "333338" if dark else "D8D7D0"
    title_color = accent if dark else "0B0B0B"
    body_color = "D9D9D5" if dark else "383834"
    return text_box(
        x,
        y,
        w,
        h,
        [para(title, 2100, title_color, True), para(body, 1600, body_color)],
        fill=bg,
        line=border,
        radius=True,
    )


def slide_xml(slide: dict, idx: int) -> str:
    global _next_id
    _next_id.value = 1
    dark = slide.get("dark", True)
    bg = "080808" if dark else "F8F7F2"
    fg = "F7F7F2" if dark else "0B0B0B"
    muted = "C9C9C5" if dark else "3A3A35"
    shapes = [rect(0, 0, 13.333, 7.5, bg)]
    shapes.append(text_box(0.65, 0.38, 3.2, 0.32, [para(slide["kicker"], 1050, "D7FF21", True)]))
    shapes.append(text_box(10.85, 0.34, 1.65, 0.36, [para("co-Suite", 1450, fg, True)]))
    shapes.append(text_box(0.65, 1.05, 9.65, 1.35, [para(slide["title"], slide.get("title_size", 3400), fg, True)]))
    if slide.get("lead"):
        shapes.append(text_box(0.69, 2.45, 10.2, 0.85, [para(slide["lead"], 1750, muted)]))
    for item in slide.get("bullets", []):
        pass
    if slide.get("bullets"):
        y = 3.25 if slide.get("lead") else 2.55
        shapes.append(text_box(0.75, y, 10.8, 3.2, [para(b, 1550, muted, bullet=True) for b in slide["bullets"]]))
    for c in slide.get("cards", []):
        shapes.append(card(*c, dark=dark))
    if slide.get("table"):
        left, right = slide["table"]
        rows = [("Generic AI tools", "co-Suite"), *zip(left, right)]
        y = 2.35
        for i, row in enumerate(rows):
            size = 1350 if i else 1250
            color = "D7FF21" if i == 0 else muted
            shapes.append(text_box(0.85, y, 5.1, 0.38, [para(row[0], size, color, i == 0)], fill=None))
            shapes.append(text_box(6.25, y, 5.65, 0.38, [para(row[1], size, color, i == 0)], fill=None))
            shapes.append(rect(0.85, y + 0.43, 11.1, 0.012, "333338" if dark else "D8D7D0"))
            y += 0.55
    if idx in (1, len(SLIDES)):
        shapes.extend([rect(0.65, 6.78, 3.8, 0.07, "D7FF21"), rect(4.55, 6.78, 3.8, 0.07, "FF4FA3"), rect(8.45, 6.78, 3.8, 0.07, "2F80FF")])
    shapes.append(text_box(0.65, 7.05, 5.2, 0.22, [para("Confidential · Investor narrative draft", 850, "777777")]))
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
    <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
    {''.join(shapes)}
  </p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>"""


SLIDES = [
    {"kicker": "Confidential investor narrative · June 2026", "title": "The AI marketing operating system for every business", "lead": "co-Suite turns a business's website, social pages, brand assets, products, audience, and connected ad accounts into a living marketing workspace.", "title_size": 3900},
    {"kicker": "Problem", "title": "Small businesses do not have a marketing operating system.", "dark": False, "cards": [(0.85, 2.65, 3.65, 1.55, "Too expensive", "Hiring a full marketing team is out of reach before the business proves growth."), (4.85, 2.65, 3.65, 1.55, "Too generic", "AI tools generate content, but do not understand the business, language, brand, audience, or market."), (8.85, 2.65, 3.65, 1.55, "Too fragmented", "Work is scattered across social apps, ad managers, design tools, calendars, spreadsheets, and chat.")]},
    {"kicker": "Insight", "title": "The bottleneck is not content generation. It is business understanding.", "lead": "Generic AI can create a post. It cannot reliably know what this business sells, who the audience is, what language to use, or what the user approved last time.", "cards": [(0.9, 4.05, 5.2, 1.35, "Without memory", "Every prompt starts from zero. Quality depends on how well the user explains the business again."), (6.55, 4.05, 5.2, 1.35, "With Suite Memory", "Every post, image, video, campaign, and schedule is grounded in the business profile, brand, audience, and feedback history.")]},
    {"kicker": "Solution", "title": "One suite per business. One memory. Many workflows.", "cards": [(0.85, 2.7, 3.65, 1.65, "Business brain", "Business profile, category, services, products, audience, USP, ESP, and marketing message."), (4.85, 2.7, 3.65, 1.65, "Brand brain", "Logos, colors, fonts, visual rules, personas, content tone, language rules, and feedback learnings."), (8.85, 2.7, 3.65, 1.65, "Operating brain", "Connected platforms, analytics, generated content, calendars, campaigns, product bulk jobs, publishing status.")]},
    {"kicker": "Product flow", "title": "From onboarding to daily marketing operations.", "dark": False, "cards": [(0.85, 2.45, 5.35, 1.35, "1. Build the Suite", "Read website and social links, extract business intelligence, and guide profile confirmation step by step."), (6.55, 2.45, 5.35, 1.35, "2. Operate the Suite", "Generate, review, edit, approve, schedule, publish, analyze, and improve future rules."), (0.85, 4.15, 5.35, 1.35, "3. Expand workflows", "Product creatives, carousels, videos, sponsored campaigns, social calendar loops, and agency operations."), (6.55, 4.15, 5.35, 1.35, "4. Keep learning", "Every approval, rejection, upload, campaign, and platform connection strengthens the Suite Memory.")]},
    {"kicker": "Why now", "title": "AI creation is becoming cheap. Context and workflow are the defensible layer.", "bullets": ["Text, image, and video generation models are improving quickly.", "Small businesses still need control, approvals, scheduling, platform connections, and analytics.", "Multilingual local markets need Arabic, Hebrew, English, and additional languages as native product experiences.", "The winning product is not one model. It is the operating layer around many models and platforms."]},
    {"kicker": "Wedge", "title": "Start with multilingual SMBs and agencies in Israel and nearby markets.", "dark": False, "cards": [(0.85, 2.65, 3.65, 1.55, "SMBs", "Need consistent content, simple campaigns, clear analytics, and brand discipline without hiring a full team."), (4.85, 2.65, 3.65, 1.55, "Creators", "Need voice, persona references, video/carousel output, and rules for what to say or avoid."), (8.85, 2.65, 3.65, 1.55, "Agencies", "Need faster onboarding, bulk generation, review flows, and multi-client operations.")]},
    {"kicker": "Differentiation", "title": "co-Suite is not a post generator.", "table": (["Prompt-by-prompt", "Mostly English-first", "Detached from platforms", "One-off outputs", "No business setup", "Weak feedback loop"], ["Persistent Suite Memory", "Native multilingual product and generation", "Meta, Instagram, Google Ads, storage, publishing", "Pending, approved, scheduled, published lifecycle", "AI-assisted business and brand profile", "Rejection and edits become rules"])},
    {"kicker": "Capabilities", "title": "The platform already spans the core marketing workflow.", "cards": [(0.85, 2.65, 3.65, 1.65, "Onboarding intelligence", "Reads websites/social pages and extracts category, services, audience, language, and brand signals."), (4.85, 2.65, 3.65, 1.65, "Generation", "Ideas, captions, images, carousels, videos, product bulk creatives, and regeneration with feedback."), (8.85, 2.65, 3.65, 1.65, "Connections", "Meta/Facebook/Instagram, Meta Ads, Google Ads, R2 media storage, publishing and analytics foundations.")]},
    {"kicker": "Business model", "title": "Subscription plus usage-based AI and media generation.", "dark": False, "cards": [(0.85, 2.65, 3.65, 1.65, "Subscription", "Monthly pricing per Suite, with agency tier for multiple client Suites and team seats."), (4.85, 2.65, 3.65, 1.65, "Usage credits", "Variable AI cost covered through credits for images, videos, bulk jobs, and premium generation."), (8.85, 2.65, 3.65, 1.65, "Add-ons", "Campaign builder, automation loops, advanced analytics, agency operations, and managed workflows.")]},
    {"kicker": "Moat", "title": "The moat is compound memory plus workflow distribution.", "lead": "The product improves every time the user approves, edits, rejects, connects, uploads, publishes, or analyzes.", "cards": [(0.85, 3.8, 3.65, 1.35, "Data asset", "Business profile, product catalog, brand assets, language rules, and audience definitions."), (4.85, 3.8, 3.65, 1.35, "Workflow lock-in", "Content lifecycle, campaign surfaces, calendars, publishing, analytics, and feedback rules."), (8.85, 3.8, 3.65, 1.35, "Local advantage", "Arabic, Hebrew, English, and multilingual market behavior as first-class assumptions.")]},
    {"kicker": "Architecture", "title": "Built as a Suite-centric AI workflow platform.", "cards": [(0.9, 2.95, 5.2, 1.6, "Current stack", "Next.js web app, FastAPI backend, Suite/ContentPost/GenerationJob/ProductBulk models, R2 storage, Meta and Google integrations."), (6.55, 2.95, 5.2, 1.6, "Architecture direction", "Every workflow reads from Suite Memory through a canonical context builder and writes back artifacts, analytics, and feedback learnings.")]},
    {"kicker": "Roadmap", "title": "From rich prototype to scalable operating system.", "dark": False, "cards": [(0.85, 2.65, 3.65, 1.65, "Near term", "Harden onboarding diagnostics, generation jobs, provider limits, editing, approvals, schedule, publish, and mobile UX."), (4.85, 2.65, 3.65, 1.65, "Next", "Social Calendar Builder, Sponsored Campaign Builder, better product bulk workflows, analytics surfaces, agency workspace."), (8.85, 2.65, 3.65, 1.65, "Platform", "Native iOS/Android companion apps, more ad platforms, vertical templates, deeper automation loops.")]},
    {"kicker": "Investment use", "title": "Funding accelerates product stability, integrations, and go-to-market.", "cards": [(0.85, 2.65, 3.65, 1.65, "Engineering", "Job queues, provider orchestration, testing, security, scaling, and reliability."), (4.85, 2.65, 3.65, 1.65, "Product", "Polished onboarding, mobile approvals, calendar builder, campaign builder, and agency flows."), (8.85, 2.65, 3.65, 1.65, "GTM", "Pilot agencies, SMB verticals, onboarding playbooks, customer success, and pricing validation.")]},
    {"kicker": "The ask", "title": "We are building the marketing operating system for the AI-native business era.", "lead": "co-Suite sits at the intersection of SMB marketing pain, multilingual local markets, AI media generation, ad platform workflows, and agency production bottlenecks.", "bullets": ["Seeking strategic capital and partners.", "Immediate goal: turn the working platform into a reliable daily product for agencies and businesses.", "The next wave is not just generating content; it is operating marketing systems around business memory."]},
]


def content_types() -> str:
    slides = "\n".join(
        f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for i in range(1, len(SLIDES) + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  {slides}
</Types>"""


def presentation_xml() -> str:
    slide_ids = "\n".join(
        f'<p:sldId id="{255 + i}" r:id="rId{i}"/>' for i in range(1, len(SLIDES) + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
 <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId{len(SLIDES)+1}"/></p:sldMasterIdLst>
 <p:sldIdLst>{slide_ids}</p:sldIdLst>
 <p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}" type="wide"/>
 <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>"""


def presentation_rels() -> str:
    slide_rels = "\n".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>'
        for i in range(1, len(SLIDES) + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 {slide_rels}
 <Relationship Id="rId{len(SLIDES)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>
 <Relationship Id="rId{len(SLIDES)+2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>
</Relationships>"""


ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
 <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
 <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
 <dc:title>co-Suite Investor Deck</dc:title><dc:creator>co-Suite</dc:creator>
 <cp:lastModifiedBy>co-Suite</cp:lastModifiedBy>
 <dcterms:created xsi:type="dcterms:W3CDTF">2026-06-05T00:00:00Z</dcterms:created>
 <dcterms:modified xsi:type="dcterms:W3CDTF">2026-06-05T00:00:00Z</dcterms:modified>
</cp:coreProperties>"""

APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
 <Application>co-Suite</Application><PresentationFormat>Widescreen</PresentationFormat>
 <Slides>15</Slides></Properties>"""

MASTER = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
 <p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
 <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
 </p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
 <p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
</p:sldMaster>"""

MASTER_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
 <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>"""

LAYOUT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">
 <p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
 <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
 </p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>"""

LAYOUT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""

SLIDE_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>"""

THEME = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="co-Suite">
 <a:themeElements><a:clrScheme name="co-Suite"><a:dk1><a:srgbClr val="050505"/></a:dk1><a:lt1><a:srgbClr val="F8F7F2"/></a:lt1><a:dk2><a:srgbClr val="111113"/></a:dk2><a:lt2><a:srgbClr val="F1F0EA"/></a:lt2><a:accent1><a:srgbClr val="D7FF21"/></a:accent1><a:accent2><a:srgbClr val="FF4FA3"/></a:accent2><a:accent3><a:srgbClr val="2F80FF"/></a:accent3><a:accent4><a:srgbClr val="00A676"/></a:accent4><a:accent5><a:srgbClr val="FFFFFF"/></a:accent5><a:accent6><a:srgbClr val="777777"/></a:accent6><a:hlink><a:srgbClr val="2F80FF"/></a:hlink><a:folHlink><a:srgbClr val="FF4FA3"/></a:folHlink></a:clrScheme>
 <a:fontScheme name="Inter"><a:majorFont><a:latin typeface="Arial"/></a:majorFont><a:minorFont><a:latin typeface="Arial"/></a:minorFont></a:fontScheme><a:fmtScheme name="co-Suite"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements>
</a:theme>"""


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUT, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types())
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("docProps/core.xml", CORE)
        z.writestr("docProps/app.xml", APP)
        z.writestr("ppt/presentation.xml", presentation_xml())
        z.writestr("ppt/_rels/presentation.xml.rels", presentation_rels())
        z.writestr("ppt/slideMasters/slideMaster1.xml", MASTER)
        z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", MASTER_RELS)
        z.writestr("ppt/slideLayouts/slideLayout1.xml", LAYOUT)
        z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", LAYOUT_RELS)
        z.writestr("ppt/theme/theme1.xml", THEME)
        for i, slide in enumerate(SLIDES, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", slide_xml(slide, i))
            z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", SLIDE_RELS)
    print(OUT)


if __name__ == "__main__":
    main()
