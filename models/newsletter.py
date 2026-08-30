"""Pydantic v2 models for the BVM e.V. quarterly newsletter.

Every model here has a hand-written TS mirror in frontend/src/lib/types.ts —
keep the pair in sync in the same edit.
"""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class NewsletterItem(BaseModel):
    """One normalised Event or Blog entry."""
    uid: str
    source_id: str
    kind: Literal["event", "blog"]
    title: str
    date: str                      # ISO date-time string, as published
    category: str = ""
    stream: str = ""
    location: str = ""
    summary: str = ""
    body: str = ""
    highlights: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    image: str = ""
    image_from_fallback: bool = False
    author: str = ""
    partner_name: str = ""
    partner_url: str = ""
    audience: str = ""
    in_window: bool = False
    upcoming: bool = False


class Inventory(BaseModel):
    months: int
    window_start: str
    window_end: str
    generated_at: str
    source_base: str
    events: List[NewsletterItem]
    blogs: List[NewsletterItem]
    upcoming: List[NewsletterItem]
    total_events: int
    total_blogs: int
    blogs_fallback_used: bool = False


class Newsletter(BaseModel):
    id: str
    issue_title: str
    issue_period: str
    months: int
    window_start: str
    window_end: str
    generated_at: str
    source_base: str
    editorial: str
    editorial_source: Literal["ai", "fallback"]
    events: List[NewsletterItem]
    blogs: List[NewsletterItem]
    upcoming: List[NewsletterItem]
    teaser_intro: str
    design_notes: List[str]
    pdf_ready: bool = False
    pdf_pages: int = 0
    pdf_bytes: int = 0
    blogs_fallback_used: bool = False


class BuildRequest(BaseModel):
    months: int = 3
    source_base: Optional[str] = None
    use_ai_editorial: bool = True


class EditorialRequest(BaseModel):
    tone_hint: str = ""


class EditorialResponse(BaseModel):
    editorial: str
    editorial_source: Literal["ai", "fallback"]
    generated_at: datetime
