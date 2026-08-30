"""Newsletter routes — mounted onto api_router (so every path lives under /api)."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from lib import sources
from lib.editorial import fallback_editorial, generate_editorial
from lib.pdf_builder import DESIGN_NOTES, MONTHS_DE, build_pdf
from models.newsletter import (
    BuildRequest,
    EditorialRequest,
    EditorialResponse,
    Inventory,
    Newsletter,
    NewsletterItem,
)
from lib.db import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/newsletter", tags=["newsletter"])

PDF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "generated")
PDF_PATH = os.path.join(PDF_DIR, "bvm-newsletter-latest.pdf")
CURRENT_ID = "current"


def _now() -> datetime:
    return datetime.utcnow()


def _period_label(start: str, end: str) -> str:
    try:
        s = datetime.strptime(start, "%Y-%m-%d")
        e = datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        return f"{start} – {end}"
    if s.year == e.year:
        return f"{MONTHS_DE[s.month - 1]} – {MONTHS_DE[e.month - 1]} {e.year}"
    return f"{MONTHS_DE[s.month - 1]} {s.year} – {MONTHS_DE[e.month - 1]} {e.year}"


def _issue_title(inv: Dict[str, Any]) -> str:
    tags: List[str] = []
    for item in inv["events"] + inv["blogs"]:
        tags.extend(t for t in item.get("tags", []) if t)
    lowered = " ".join(tags).lower()
    if "dialog" in lowered:
        return "Vielfalt verbindet"
    if "kultur" in lowered:
        return "Gemeinsam Kultur leben"
    return "Miteinander in Mittelhessen"


def _teaser_intro(upcoming: List[Dict[str, Any]]) -> str:
    if not upcoming:
        return (
            "Die nächsten Termine planen wir gerade mit Herzblut – schau bald wieder "
            "auf unserer Website vorbei, wir freuen uns auf dich!"
        )
    return (
        f"Es bleibt lebendig: {len(upcoming)} neue Begegnungen stehen schon in unserem "
        "Kalender. Merk dir die Termine vor, bring gute Laune mit – und am besten "
        "jemanden, der uns noch nicht kennt."
    )


async def _assemble(months: int, source_base: str | None, use_ai: bool) -> Dict[str, Any]:
    raw_events, raw_blogs, base = await sources.fetch_raw(source_base)
    if not raw_events and not raw_blogs:
        raise HTTPException(
            status_code=502,
            detail="Die Datenquellen (events.json / blogs.json) konnten nicht geladen werden.",
        )
    inv = sources.build_inventory(raw_events, raw_blogs, months, _now())
    period = _period_label(inv["window_start"], inv["window_end"])
    if use_ai:
        editorial, src = await generate_editorial(
            inv["events"], inv["blogs"], inv["upcoming"], period
        )
    else:
        editorial, src = fallback_editorial(inv["events"], inv["blogs"], period), "fallback"

    doc: Dict[str, Any] = {
        "id": CURRENT_ID,
        "issue_title": _issue_title(inv),
        "issue_period": period,
        "months": months,
        "window_start": inv["window_start"],
        "window_end": inv["window_end"],
        "generated_at": _now().isoformat(),
        "source_base": base,
        "editorial": editorial,
        "editorial_source": src,
        "events": inv["events"],
        "blogs": inv["blogs"],
        "upcoming": inv["upcoming"],
        "teaser_intro": _teaser_intro(inv["upcoming"]),
        "design_notes": DESIGN_NOTES,
        "blogs_fallback_used": inv["blogs_fallback_used"],
        "pdf_ready": False,
        "pdf_pages": 0,
        "pdf_bytes": 0,
    }
    pages, size = await build_pdf(doc, PDF_PATH)
    doc.update({"pdf_ready": True, "pdf_pages": pages, "pdf_bytes": size})
    await db.newsletters.replace_one({"id": CURRENT_ID}, doc, upsert=True)
    return doc


@router.post("/build", response_model=Newsletter)
async def build_newsletter(payload: BuildRequest):
    months = max(1, min(payload.months, 24))
    return Newsletter(**await _assemble(months, payload.source_base, payload.use_ai_editorial))


@router.get("/current", response_model=Newsletter)
async def current_newsletter(months: int = Query(3, ge=1, le=24)):
    """The published issue. Whatever the Redaktion last built is what visitors see;
    `months` only seeds the very first build."""
    doc = await db.newsletters.find_one({"id": CURRENT_ID}, {"_id": 0})
    if doc and os.path.exists(PDF_PATH):
        return Newsletter(**doc)
    return Newsletter(**await _assemble(months, None, True))


@router.get("/inventory", response_model=Inventory)
async def inventory(months: int = Query(3, ge=1, le=24), source_base: str | None = None):
    raw_events, raw_blogs, base = await sources.fetch_raw(source_base)
    if not raw_events and not raw_blogs:
        raise HTTPException(status_code=502, detail="Datenquellen nicht erreichbar.")
    inv = sources.build_inventory(raw_events, raw_blogs, months, _now())
    return Inventory(
        months=months,
        window_start=inv["window_start"],
        window_end=inv["window_end"],
        generated_at=_now().isoformat(),
        source_base=base,
        events=[NewsletterItem(**e) for e in inv["events"]],
        blogs=[NewsletterItem(**b) for b in inv["blogs"]],
        upcoming=[NewsletterItem(**u) for u in inv["upcoming"]],
        total_events=inv["total_events"],
        total_blogs=inv["total_blogs"],
        blogs_fallback_used=inv["blogs_fallback_used"],
    )


@router.post("/editorial", response_model=EditorialResponse)
async def regenerate_editorial(payload: EditorialRequest):
    doc = await db.newsletters.find_one({"id": CURRENT_ID}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Noch keine Ausgabe erstellt.")
    editorial, src = await generate_editorial(
        doc["events"], doc["blogs"], doc["upcoming"], doc["issue_period"], payload.tone_hint
    )
    doc["editorial"] = editorial
    doc["editorial_source"] = src
    doc["generated_at"] = _now().isoformat()
    pages, size = await build_pdf(doc, PDF_PATH)
    doc.update({"pdf_ready": True, "pdf_pages": pages, "pdf_bytes": size})
    await db.newsletters.replace_one({"id": CURRENT_ID}, doc, upsert=True)
    return EditorialResponse(editorial=editorial, editorial_source=src, generated_at=_now())


@router.get("/download")
async def download_pdf():
    if not os.path.exists(PDF_PATH):
        await _assemble(3, None, True)
    if not os.path.exists(PDF_PATH):
        raise HTTPException(status_code=404, detail="PDF nicht verfügbar.")
    return FileResponse(
        PDF_PATH,
        media_type="application/pdf",
        filename="bvm-newsletter-aktuell.pdf",
        headers={"Content-Disposition": 'attachment; filename="bvm-newsletter-aktuell.pdf"'},
    )
