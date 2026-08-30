"""Colourful A4 newsletter PDF, built with ReportLab Platypus.

Palette and layout follow /app/design_guidelines.json:
terracotta #C0431D, forest #1E3D34, amber #D97706 on cream #FAF8F5.
"""
from __future__ import annotations

import io
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

import httpx
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

TERRACOTTA = colors.HexColor("#C0431D")
FOREST = colors.HexColor("#1E3D34")
AMBER = colors.HexColor("#D97706")
CREAM = colors.HexColor("#FAF8F5")
CHARCOAL = colors.HexColor("#1C1B1F")
MUTED = colors.HexColor("#57534E")
BORDER = colors.HexColor("#E7E5E4")
EDITORIAL_BG = colors.HexColor("#FFF8F0")

PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

MONTHS_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]

_FONTS_READY = False


def _register_fonts() -> None:
    global _FONTS_READY
    if _FONTS_READY:
        return
    base = "/usr/share/fonts/truetype/liberation"
    pairs = [
        ("BVMSerif", "LiberationSerif-Regular.ttf"),
        ("BVMSerif-Bold", "LiberationSerif-Bold.ttf"),
        ("BVMSerif-Italic", "LiberationSerif-Italic.ttf"),
        ("BVMSans", "LiberationSans-Regular.ttf"),
        ("BVMSans-Bold", "LiberationSans-Bold.ttf"),
    ]
    try:
        for name, filename in pairs:
            pdfmetrics.registerFont(TTFont(name, os.path.join(base, filename)))
        pdfmetrics.registerFontFamily(
            "BVMSerif", normal="BVMSerif", bold="BVMSerif-Bold", italic="BVMSerif-Italic"
        )
        pdfmetrics.registerFontFamily("BVMSans", normal="BVMSans", bold="BVMSans-Bold")
        _FONTS_READY = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("TTF registration failed, falling back to core fonts: %s", exc)


def _f(serif: bool = False, bold: bool = False, italic: bool = False) -> str:
    if not _FONTS_READY:
        if serif:
            return "Times-Bold" if bold else ("Times-Italic" if italic else "Times-Roman")
        return "Helvetica-Bold" if bold else "Helvetica"
    if serif:
        return "BVMSerif-Bold" if bold else ("BVMSerif-Italic" if italic else "BVMSerif")
    return "BVMSans-Bold" if bold else "BVMSans"


def de_date(raw: str) -> str:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            d = datetime.strptime(raw.replace("Z", "")[:19], fmt)
            stamp = f"{d.day}. {MONTHS_DE[d.month - 1]} {d.year}"
            if d.hour or d.minute:
                stamp += f", {d.hour:02d}:{d.minute:02d} Uhr"
            return stamp
        except ValueError:
            continue
    return raw[:10]


def esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _styles() -> Dict[str, ParagraphStyle]:
    return {
        "cover_kicker": ParagraphStyle(
            "cover_kicker", fontName=_f(bold=True), fontSize=11, leading=16,
            textColor=colors.white, alignment=TA_CENTER,
        ),
        "cover_title": ParagraphStyle(
            "cover_title", fontName=_f(serif=True, bold=True), fontSize=40, leading=46,
            textColor=colors.white, alignment=TA_CENTER,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub", fontName=_f(serif=True, italic=True), fontSize=15, leading=22,
            textColor=colors.HexColor("#FDE7D9"), alignment=TA_CENTER,
        ),
        "h2": ParagraphStyle(
            "h2", fontName=_f(serif=True, bold=True), fontSize=22, leading=27,
            textColor=FOREST, spaceAfter=2,
        ),
        "h3": ParagraphStyle(
            "h3", fontName=_f(serif=True, bold=True), fontSize=14.5, leading=19,
            textColor=CHARCOAL, spaceAfter=1,
        ),
        "label": ParagraphStyle(
            "label", fontName=_f(bold=True), fontSize=7.6, leading=11,
            textColor=AMBER,
        ),
        "meta": ParagraphStyle(
            "meta", fontName=_f(bold=True), fontSize=8.6, leading=13, textColor=TERRACOTTA,
        ),
        "body": ParagraphStyle(
            "body", fontName=_f(), fontSize=9.6, leading=14.4, textColor=CHARCOAL,
        ),
        "body_muted": ParagraphStyle(
            "body_muted", fontName=_f(), fontSize=8.8, leading=13, textColor=MUTED,
        ),
        "editorial": ParagraphStyle(
            "editorial", fontName=_f(serif=True), fontSize=11, leading=17.5,
            textColor=CHARCOAL, alignment=TA_JUSTIFY, spaceAfter=9,
        ),
        "bullet": ParagraphStyle(
            "bullet", fontName=_f(), fontSize=9, leading=13.4, textColor=CHARCOAL,
            leftIndent=9, bulletIndent=1,
        ),
        "footer_head": ParagraphStyle(
            "footer_head", fontName=_f(bold=True), fontSize=11, leading=16,
            textColor=colors.white,
        ),
        "footer_body": ParagraphStyle(
            "footer_body", fontName=_f(), fontSize=9, leading=14,
            textColor=colors.HexColor("#CFE3D8"),
        ),
    }


async def _load_images(items: List[Dict[str, Any]]) -> Dict[str, bytes]:
    urls = {i["image"] for i in items if i.get("image")}
    out: Dict[str, bytes] = {}
    if not urls:
        return out
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for url in urls:
            try:
                resp = await client.get(url)
                if resp.status_code == 200 and resp.content:
                    out[url] = resp.content
            except httpx.HTTPError:
                continue
    return out


def _image_flowable(blob: bytes | None, width: float, height: float):
    if not blob:
        return None
    try:
        from PIL import Image as PILImage

        src = PILImage.open(io.BytesIO(blob)).convert("RGB")
        target_ratio = width / height
        w, h = src.size
        if w / h > target_ratio:            # too wide -> crop sides
            new_w = int(h * target_ratio)
            left = (w - new_w) // 2
            src = src.crop((left, 0, left + new_w, h))
        else:                                # too tall -> crop top/bottom
            new_h = int(w / target_ratio)
            top = int((h - new_h) * 0.25)
            src = src.crop((0, top, w, top + new_h))
        src = src.resize((int(width * 2), int(height * 2)), PILImage.LANCZOS)
        buf = io.BytesIO()
        src.save(buf, format="JPEG", quality=82)
        buf.seek(0)
        return Image(buf, width=width, height=height)
    except Exception as exc:  # noqa: BLE001
        logger.warning("image render failed: %s", exc)
        return None


def _pill_row(tags: List[str], styles) -> Table | None:
    tags = [t for t in tags if t][:4]
    if not tags:
        return None
    cells = [
        Paragraph(f"<font color='#1E3D34'>{esc(t.upper())}</font>", styles["label"])
        for t in tags
    ]
    table = Table([cells], colWidths=[None] * len(cells), hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EAF1EC")),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#CFE0D4")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.white),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _section_header(number: str, title: str, subtitle: str, accent, styles) -> Table:
    left = Paragraph(f"<font color='white'><b>{esc(number)}</b></font>",
                     ParagraphStyle("num", parent=styles["h2"], alignment=TA_CENTER,
                                    fontSize=18, leading=22, textColor=colors.white))
    right_bits = [Paragraph(esc(title), styles["h2"])]
    if subtitle:
        right_bits.append(Paragraph(esc(subtitle), styles["body_muted"]))
    table = Table([[left, right_bits]], colWidths=[14 * mm, CONTENT_W - 14 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), accent),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 0),
                ("LEFTPADDING", (1, 0), (1, 0), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LINEBELOW", (1, 0), (1, 0), 1.6, accent),
            ]
        )
    )
    return table


def _entry_card(item: Dict[str, Any], images: Dict[str, bytes], styles, accent) -> KeepTogether:
    img_w = 44 * mm
    img = _image_flowable(images.get(item.get("image", "")), img_w, 32 * mm)

    right: List[Any] = []
    kicker_bits = [de_date(item.get("date", ""))]
    if item.get("location"):
        kicker_bits.append(item["location"])
    if item.get("partner_name"):
        kicker_bits.append(item["partner_name"])
    elif item.get("author"):
        kicker_bits.append(item["author"])
    right.append(Paragraph(esc("  •  ".join(kicker_bits)), styles["meta"]))
    right.append(Paragraph(esc(item.get("title", "")), styles["h3"]))
    if item.get("summary"):
        right.append(Paragraph(esc(item["summary"][:400]), styles["body"]))
    if item.get("highlights"):
        right.append(Spacer(1, 3))
        for h in item["highlights"][:4]:
            right.append(Paragraph(esc(h), styles["bullet"], bulletText="\u25aa"))
    pills = _pill_row(item.get("tags", []), styles)
    if pills:
        right.append(Spacer(1, 4))
        right.append(pills)
    if item.get("audience"):
        right.append(Spacer(1, 3))
        right.append(Paragraph(f"<i>{esc(item['audience'])}</i>", styles["body_muted"]))

    if img:
        cells = [[img, right]]
        widths = [img_w, CONTENT_W - img_w - 6 * mm]
    else:
        cells = [[right]]
        widths = [CONTENT_W - 6 * mm]

    card = Table(cells, colWidths=widths)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("LINEBEFORE", (0, 0), (0, -1), 2.4, accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]
    if img:
        style += [("LEFTPADDING", (1, 0), (1, 0), 8)]
    card.setStyle(TableStyle(style))
    return KeepTogether([card, Spacer(1, 6 * mm)])


def _cover_canvas(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(TERRACOTTA)
    canvas.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    # Deep forest diagonal band
    canvas.setFillColor(FOREST)
    p = canvas.beginPath()
    p.moveTo(0, PAGE_H * 0.34)
    p.lineTo(PAGE_W, PAGE_H * 0.46)
    p.lineTo(PAGE_W, 0)
    p.lineTo(0, 0)
    p.close()
    canvas.drawPath(p, stroke=0, fill=1)
    # Amber accent shapes
    canvas.setFillColor(AMBER)
    canvas.circle(PAGE_W * 0.86, PAGE_H * 0.9, 26 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor("#E9764A"))
    canvas.circle(PAGE_W * 0.12, PAGE_H * 0.2, 18 * mm, stroke=0, fill=1)
    canvas.setFillColor(CREAM)
    canvas.circle(PAGE_W * 0.93, PAGE_H * 0.13, 10 * mm, stroke=0, fill=1)
    canvas.restoreState()


def _inner_canvas(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(CREAM)
    canvas.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    # top rule with three colour ticks
    canvas.setFillColor(TERRACOTTA)
    canvas.rect(0, PAGE_H - 6 * mm, PAGE_W / 3, 3, stroke=0, fill=1)
    canvas.setFillColor(AMBER)
    canvas.rect(PAGE_W / 3, PAGE_H - 6 * mm, PAGE_W / 3, 3, stroke=0, fill=1)
    canvas.setFillColor(FOREST)
    canvas.rect(2 * PAGE_W / 3, PAGE_H - 6 * mm, PAGE_W / 3, 3, stroke=0, fill=1)

    canvas.setFont(_f(bold=True), 7.6)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, PAGE_H - 11 * mm, "BVM e.V. GIESSEN — QUARTALS-NEWSLETTER")
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 11 * mm, "bvm-ev.de")

    canvas.setFont(_f(), 7.6)
    canvas.drawString(MARGIN, 9 * mm, "Kontakt: info@bvm-ev.de")
    canvas.setFillColor(TERRACOTTA)
    canvas.setFont(_f(bold=True), 8.4)
    canvas.drawRightString(PAGE_W - MARGIN, 9 * mm, f"Seite {canvas.getPageNumber() - 1}")
    canvas.restoreState()


def _footer_block(styles) -> Table:
    col1 = [
        Paragraph("BVM e.V. Gießen", styles["footer_head"]),
        Paragraph(
            "Bund der Vereine für<br/>Multikulturelles Miteinander<br/>Mittelhessen",
            styles["footer_body"],
        ),
    ]
    col2 = [
        Paragraph("Kontakt", styles["footer_head"]),
        Paragraph(
            "info@bvm-ev.de<br/>bvm-ev.de<br/>Gießen, Hessen",
            styles["footer_body"],
        ),
    ]
    col3 = [
        Paragraph("Mitmachen", styles["footer_head"]),
        Paragraph(
            "Events: /events.html<br/>Blog: /blog.html<br/>Newsletter: /newsletter",
            styles["footer_body"],
        ),
    ]
    table = Table([[col1, col2, col3]], colWidths=[CONTENT_W / 3.0] * 3)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), FOREST),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
            ]
        )
    )
    return table


async def build_pdf(newsletter: Dict[str, Any], out_path: str) -> tuple[int, int]:
    """Render the newsletter to `out_path`. Returns (pages, bytes)."""
    _register_fonts()
    styles = _styles()
    events = newsletter.get("events", [])
    blogs = newsletter.get("blogs", [])
    upcoming = newsletter.get("upcoming", [])
    images = await _load_images(events + blogs + upcoming)

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        title=newsletter.get("issue_title", "BVM Newsletter"),
        author="BVM e.V. Gießen",
        subject="Quartals-Newsletter",
    )
    cover_frame = Frame(MARGIN, PAGE_H * 0.30, CONTENT_W, PAGE_H * 0.46, id="cover")
    inner_frame = Frame(MARGIN, 14 * mm, CONTENT_W, PAGE_H - 14 * mm - 16 * mm, id="inner")
    doc.addPageTemplates(
        [
            PageTemplate(id="Cover", frames=[cover_frame], onPage=_cover_canvas),
            PageTemplate(id="Inner", frames=[inner_frame], onPage=_inner_canvas),
        ]
    )

    story: List[Any] = []

    # --- 1. Cover -----------------------------------------------------------
    story.append(Paragraph("BVM e.V. GIESSEN &nbsp;•&nbsp; QUARTALS-NEWSLETTER", styles["cover_kicker"]))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(esc(newsletter.get("issue_title", "")), styles["cover_title"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(esc(newsletter.get("issue_period", "")), styles["cover_sub"]))
    story.append(Spacer(1, 8 * mm))
    stats = Paragraph(
        f"{len(events)} Events &nbsp;&nbsp;|&nbsp;&nbsp; {len(blogs)} Blogbeiträge"
        f" &nbsp;&nbsp;|&nbsp;&nbsp; {len(upcoming)} Vorschau",
        styles["cover_kicker"],
    )
    story.append(stats)
    story.append(Spacer(1, 10 * mm))
    story.append(
        Paragraph(
            "Editorial der Redaktion &nbsp;·&nbsp; Rückblick Events &nbsp;·&nbsp; "
            "Stimmen aus dem Blog &nbsp;·&nbsp; Was kommt als Nächstes",
            ParagraphStyle("toc", parent=styles["cover_sub"], fontSize=10.5, leading=16),
        )
    )
    story.append(NextPageTemplate("Inner"))
    story.append(PageBreak())

    # --- 2. Editorial der Redaktion ----------------------------------------
    story.append(_section_header("01", "Editorial der Redaktion", "Ein Gruß aus dem Vereinsherzen", TERRACOTTA, styles))
    story.append(Spacer(1, 5 * mm))
    editorial_paras = [
        Paragraph(esc(p.strip()), styles["editorial"])
        for p in newsletter.get("editorial", "").split("\n")
        if p.strip()
    ]
    quote = Paragraph(
        "<font size='30' color='#C0431D'><b>&#8220;</b></font>",
        ParagraphStyle("q", fontName=_f(serif=True, bold=True), fontSize=30, leading=30),
    )
    box = Table([[quote], [editorial_paras]], colWidths=[CONTENT_W])
    box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), EDITORIAL_BG),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#F1D9C4")),
                ("LINEBEFORE", (0, 0), (0, -1), 3, AMBER),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (0, 0), 6),
                ("BOTTOMPADDING", (0, 0), (0, 0), 0),
                ("BOTTOMPADDING", (0, 1), (0, 1), 10),
            ]
        )
    )
    story.append(box)
    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(
            "Herzlich, Ihre Redaktion — BVM e.V. Gießen",
            ParagraphStyle("sig", fontName=_f(serif=True, italic=True), fontSize=10.5,
                           textColor=TERRACOTTA),
        )
    )
    story.append(Spacer(1, 9 * mm))

    # --- 3. Events (chronological) -----------------------------------------
    story.append(
        _section_header(
            "02",
            "Unsere Events",
            f"Chronologisch: {newsletter.get('issue_period', '')}",
            FOREST,
            styles,
        )
    )
    story.append(Spacer(1, 5 * mm))
    if events:
        for item in events:
            story.append(_entry_card(item, images, styles, TERRACOTTA))
    else:
        story.append(Paragraph("In diesem Zeitraum gab es keine Veranstaltungen.", styles["body_muted"]))
        story.append(Spacer(1, 6 * mm))

    # --- 4. Blogs (chronological) ------------------------------------------
    story.append(PageBreak())
    story.append(
        _section_header("03", "Stimmen aus dem Blog", "Beiträge unserer Partnervereine", AMBER, styles)
    )
    story.append(Spacer(1, 5 * mm))
    if newsletter.get("blogs_fallback_used"):
        story.append(
            Paragraph(
                "Im Berichtszeitraum sind keine neuen Blogbeiträge erschienen — "
                "wir zeigen die aktuellsten Beiträge unserer Partnervereine.",
                styles["body_muted"],
            )
        )
        story.append(Spacer(1, 4 * mm))
    if blogs:
        for item in blogs:
            story.append(_entry_card(item, images, styles, AMBER))
    else:
        story.append(Paragraph("Aktuell liegen keine Blogbeiträge vor.", styles["body_muted"]))
        story.append(Spacer(1, 6 * mm))

    # --- 5. What's coming next ---------------------------------------------
    story.append(_section_header("04", "Was kommt als Nächstes?", "Termine zum Vormerken", TERRACOTTA, styles))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(esc(newsletter.get("teaser_intro", "")), styles["body"]))
    story.append(Spacer(1, 5 * mm))
    if upcoming:
        rows = [
            [
                Paragraph(f"<b>{esc(de_date(u.get('date', '')))}</b>", styles["meta"]),
                Paragraph(esc(u.get("title", "")), styles["h3"]),
                Paragraph(esc(u.get("location", "")), styles["body_muted"]),
            ]
            for u in upcoming
        ]
        table = Table(rows, colWidths=[42 * mm, CONTENT_W - 88 * mm, 46 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(table)
    else:
        story.append(Paragraph("Neue Termine folgen in Kürze auf unserer Website.", styles["body_muted"]))
    story.append(Spacer(1, 10 * mm))

    # --- 6. Footer ----------------------------------------------------------
    story.append(_footer_block(styles))

    doc.build(story)
    data = buf.getvalue()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(data)
    return doc.page, len(data)


DESIGN_NOTES = [
    "Cover: Terrakotta-Vollfläche mit tiefgrünem Diagonalband und Safran-Kreisen – "
    "farbenfroh, modern, ohne Stockfoto-Beliebigkeit.",
    "Palette: Terrakotta #C0431D (Akzente), Waldgrün #1E3D34 (Tiefe), Safran #D97706 "
    "(Highlights) auf warmem Creme #FAF8F5.",
    "Typografie: Serif (Lora-Anmutung) für Titel und Editorial, klare Sans für Metadaten "
    "und Fließtext – ruhige Hierarchie, gute Lesbarkeit.",
    "Sektionen: nummerierte Farbmarken (01–04) mit farbiger Unterlinie als Divider; "
    "jede Karte hat einen farbigen Randbalken.",
    "Karten: 44 mm Bild links (mittig beschnitten), rechts Datum/Ort, Titel, Kurztext, "
    "Highlight-Punkte und Tag-Pillen in Grün.",
    "Editorial: eigenes cremefarbenes Panel mit Anführungszeichen-Ornament, Safran-Kante "
    "und handschriftlich anmutender Signatur.",
    "Fuß: waldgrüner Footer-Block mit Kontakt, Website und Mitmach-Links; laufender "
    "Kopf/Fuß mit dreifarbigem Farbstreifen.",
]
