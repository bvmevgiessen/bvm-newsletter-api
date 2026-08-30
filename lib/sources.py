"""Fetch + normalise the BVM e.V. Events and Blogs datasets.

Authoritative sources are the JSON files in the GitHub Pages repository
(bvmevgiessen/bvm-ev-web). The repo keeps them under `src/data/`, the built
GitHub Pages site serves them under `/data/` — we try both, in order.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

import httpx

DEFAULT_SOURCE_BASE = os.environ.get(
    "NEWSLETTER_SOURCE_BASE",
    "https://raw.githubusercontent.com/bvmevgiessen/bvm-ev-web/main",
)

# Candidate relative paths per dataset, tried in order.
CANDIDATES: Dict[str, List[str]] = {
    "events": ["src/data/events.json", "data/events.json", "public/data/events.json"],
    "blogs": ["src/data/blogs.json", "data/blogs.json", "src/data/blog.json"],
}

# Curated royalty-free Unsplash header images, used when an entry ships no photo.
FALLBACK_IMAGES: List[Tuple[Tuple[str, ...], str]] = [
    (
        ("iftar", "fasten", "ramadan", "dinner", "essen", "kulinar"),
        "https://images.unsplash.com/photo-1528605248644-14dd04022da1?auto=format&fit=crop&q=80&w=1200",
    ),
    (
        ("dialog", "gespräch", "diskussion", "forum", "podium"),
        "https://images.unsplash.com/photo-1573497701240-345a300b8d36?auto=format&fit=crop&q=80&w=1200",
    ),
    (
        ("workshop", "bildung", "seminar", "schul", "lern", "projekt"),
        "https://images.unsplash.com/photo-1568992688065-536aad8a12f6?auto=format&fit=crop&q=80&w=1200",
    ),
    (
        ("fest", "kultur", "musik", "konzert", "feier"),
        "https://images.unsplash.com/photo-1516450360452-9312f5e86fc7?auto=format&fit=crop&q=80&w=1200",
    ),
    (
        ("sport", "wander", "ausflug", "natur", "garten"),
        "https://images.unsplash.com/photo-1552674605-db6ffd4facb5?auto=format&fit=crop&q=80&w=1200",
    ),
    (
        ("integration", "gesellschaft", "engagement", "ehrenamt", "nachbar"),
        "https://images.unsplash.com/photo-1521737604893-d14cc237f11d?auto=format&fit=crop&q=80&w=1200",
    ),
]

GENERIC_FALLBACK = (
    "https://images.unsplash.com/photo-1511632765486-a01980e01a18?auto=format&fit=crop&q=80&w=1200"
)


def pick_fallback_image(*texts: str) -> str:
    haystack = " ".join(t.lower() for t in texts if t)
    for keywords, url in FALLBACK_IMAGES:
        if any(k in haystack for k in keywords):
            return url
    return GENERIC_FALLBACK


def parse_date(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip().replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


async def _fetch_json(client: httpx.AsyncClient, base: str, paths: List[str]) -> List[Dict[str, Any]]:
    base = base.rstrip("/")
    for path in paths:
        try:
            resp = await client.get(f"{base}/{path}")
        except httpx.HTTPError:
            continue
        if resp.status_code != 200:
            continue
        try:
            data = resp.json()
        except ValueError:
            continue
        if isinstance(data, dict):
            for key in ("items", "events", "blogs", "posts", "data"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    return []


async def fetch_raw(source_base: str | None = None) -> Tuple[List[Dict], List[Dict], str]:
    """Return (raw_events, raw_blogs, resolved_source_base)."""
    base = (source_base or DEFAULT_SOURCE_BASE).strip().rstrip("/")
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        events = await _fetch_json(client, base, CANDIDATES["events"])
        blogs = await _fetch_json(client, base, CANDIDATES["blogs"])
    return events, blogs, base


def _clean_list(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def normalise_event(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    title = str(raw.get("title") or "Ohne Titel").strip()
    date_raw = str(raw.get("date") or "")
    source_id = str(raw.get("id") or f"event-{index}")
    image = str(raw.get("image") or "").strip()
    highlights = _clean_list(raw.get("wasErwartetSie") or raw.get("highlights"))
    tags = _clean_list(raw.get("tags"))
    category = str(raw.get("category") or "").strip()
    stream = str(raw.get("stream") or "").strip()
    if not tags:
        tags = [t for t in (category, stream) if t]
    from_fallback = not image
    return {
        "uid": f"event-{source_id}-{date_raw[:16] or index}",
        "source_id": source_id,
        "kind": "event",
        "title": title,
        "date": date_raw,
        "category": category,
        "stream": stream,
        "location": str(raw.get("location") or "").strip(),
        "summary": str(raw.get("description") or raw.get("excerpt") or "").strip(),
        "body": str(raw.get("content") or "").strip(),
        "highlights": highlights,
        "tags": tags,
        "image": image or pick_fallback_image(title, category, stream, str(raw.get("description") or "")),
        "image_from_fallback": from_fallback,
        "author": "",
        "partner_name": "",
        "partner_url": "",
        "audience": str(raw.get("fuerWen") or "").strip(),
    }


def normalise_blog(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    title = str(raw.get("title") or "Ohne Titel").strip()
    date_raw = str(raw.get("date") or raw.get("publishedAt") or "")
    source_id = str(raw.get("id") or f"blog-{index}")
    image = str(raw.get("image") or raw.get("featuredImage") or "").strip()
    excerpt = str(raw.get("excerpt") or raw.get("summary") or "").strip()
    content = str(raw.get("content") or "").strip()
    category = str(raw.get("category") or "").strip()
    tags = _clean_list(raw.get("tags")) or ([category] if category else [])
    # Key highlights for a blog: first sentences of the body.
    highlights: List[str] = []
    for chunk in content.replace("\n", " ").split(". "):
        chunk = chunk.strip().rstrip(".")
        if len(chunk) > 30:
            highlights.append(chunk + ".")
        if len(highlights) == 3:
            break
    from_fallback = not image
    return {
        "uid": f"blog-{source_id}-{date_raw[:16] or index}",
        "source_id": source_id,
        "kind": "blog",
        "title": title,
        "date": date_raw,
        "category": category,
        "stream": "",
        "location": "",
        "summary": excerpt or content[:220],
        "body": content,
        "highlights": highlights,
        "tags": tags,
        "image": image or pick_fallback_image(title, category, excerpt, " ".join(tags)),
        "image_from_fallback": from_fallback,
        "author": str(raw.get("author") or "").strip(),
        "partner_name": str(raw.get("partnerName") or "").strip(),
        "partner_url": str(raw.get("partnerUrl") or "").strip(),
        "audience": "",
    }


def build_inventory(
    raw_events: List[Dict],
    raw_blogs: List[Dict],
    months: int,
    today: datetime,
) -> Dict[str, Any]:
    """Filter into the rolling window and split events / blogs / upcoming."""
    window_start = today - timedelta(days=months * 30)
    seen: set[str] = set()

    def prepare(items: List[Dict], fn) -> List[Dict]:
        out: List[Dict] = []
        for i, raw in enumerate(items):
            item = fn(raw, i)
            if item["uid"] in seen:
                continue
            seen.add(item["uid"])
            parsed = parse_date(item["date"])
            item["_parsed"] = parsed
            item["in_window"] = bool(parsed and window_start <= parsed <= today)
            item["upcoming"] = bool(parsed and parsed > today)
            out.append(item)
        return out

    events = prepare(raw_events, normalise_event)
    blogs = prepare(raw_blogs, normalise_blog)

    def chrono(items: List[Dict], reverse: bool = False) -> List[Dict]:
        return sorted(items, key=lambda i: i["_parsed"] or datetime.min, reverse=reverse)

    window_events = chrono([e for e in events if e["in_window"]])
    window_blogs = chrono([b for b in blogs if b["in_window"]])
    blogs_fallback_used = False
    if not window_blogs and blogs:
        # No partner blog landed inside the window — show the three most recent
        # published pieces instead so the Blog section is never empty.
        blogs_fallback_used = True
        published = [b for b in blogs if not b["upcoming"]] or blogs
        window_blogs = chrono(published, reverse=True)[:3]
        window_blogs = chrono(window_blogs)

    upcoming = chrono([e for e in events if e["upcoming"]])[:4]

    for bucket in (events, blogs, window_events, window_blogs, upcoming):
        for item in bucket:
            item.pop("_parsed", None)

    return {
        "months": months,
        "window_start": window_start.date().isoformat(),
        "window_end": today.date().isoformat(),
        "events": window_events,
        "blogs": window_blogs,
        "upcoming": upcoming,
        "total_events": len(events),
        "total_blogs": len(blogs),
        "blogs_fallback_used": blogs_fallback_used,
    }
