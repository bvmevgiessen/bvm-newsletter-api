"""Subscription routes — double-opt-in, confirmation mail, and issue sending.

Mounted onto api_router, so every path lives under /api/newsletter.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import uuid
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from lib import mailer
from lib.db import db
from models.subscriber import (
    ConfirmResponse,
    SendIssueRequest,
    SendIssueResponse,
    SubscribeRequest,
    SubscribeResponse,
    Subscriber,
    SubscriberStats,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/newsletter", tags=["subscribers"])


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _public(path: str) -> str:
    base = mailer.public_base()
    return f"{base}{path}" if base else path


async def _current_issue() -> Dict[str, Any] | None:
    return await db.newsletters.find_one({"id": "current"}, {"_id": 0})


async def _send_confirmation(email: str, token: str) -> tuple[bool, str]:
    html = mailer.confirmation_html(_public(f"/api/newsletter/confirm?token={token}"))
    return await mailer.send_mail(
        email, "Bitte bestätige deine Newsletter-Anmeldung — BVM e.V. Gießen", html
    )


@router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe(payload: SubscribeRequest):
    email = payload.email.strip().lower()
    existing = await db.subscribers.find_one({"email": email}, {"_id": 0})

    if existing and existing.get("status") == "confirmed":
        return SubscribeResponse(
            status="already_confirmed",
            message="Diese E-Mail-Adresse ist bereits für unseren Newsletter angemeldet.",
            mail_sent=False,
        )

    token = existing.get("confirm_token") if existing else None
    token = token or secrets.token_urlsafe(24)
    doc = {
        "id": existing.get("id") if existing else str(uuid.uuid4()),
        "email": email,
        "status": "pending",
        "created_at": existing.get("created_at") if existing else _now_iso(),
        "confirmed_at": None,
        "last_sent_at": existing.get("last_sent_at") if existing else None,
        "send_count": existing.get("send_count", 0) if existing else 0,
        "source": payload.source,
        "confirm_token": token,
        "unsubscribe_token": (existing or {}).get("unsubscribe_token")
        or secrets.token_urlsafe(24),
    }
    await db.subscribers.replace_one({"email": email}, doc, upsert=True)

    ok, err = await _send_confirmation(email, token)
    return SubscribeResponse(
        status="resent" if existing else "pending",
        message=(
            "Fast fertig! Wir haben dir eine E-Mail geschickt — bitte bestätige dort deine "
            "Anmeldung, dann erhältst du direkt die aktuelle Ausgabe."
        )
        if ok
        else (
            "Deine Anmeldung ist gespeichert. Der Bestätigungsversand ist derzeit nicht "
            "möglich — wir melden uns, sobald der Mailversand wieder läuft."
        ),
        mail_sent=ok,
        mail_error="" if ok else err,
    )


async def _deliver_issue(sub: Dict[str, Any], issue: Dict[str, Any]) -> tuple[bool, str]:
    from routers.newsletter import PDF_PATH

    html = mailer.issue_html(
        issue,
        unsubscribe_url=_public(
            f"/api/newsletter/unsubscribe?token={sub.get('unsubscribe_token', '')}"
        ),
        download_url=_public("/api/newsletter/download"),
    )
    ok, err = await mailer.send_mail(
        sub["email"],
        f"{issue.get('issue_title', 'Newsletter')} — Ausgabe {issue.get('issue_period', '')}",
        html,
        pdf_path=PDF_PATH,
        pdf_name="bvm-newsletter-aktuell.pdf",
    )
    if ok:
        await db.subscribers.update_one(
            {"email": sub["email"]},
            {"$set": {"last_sent_at": _now_iso()}, "$inc": {"send_count": 1}},
        )
    return ok, err


@router.get("/confirm", response_model=ConfirmResponse)
async def confirm(token: str = Query(...), redirect: bool = Query(True)):
    """Double-opt-in target. Confirms, then immediately mails the current issue."""
    sub = await db.subscribers.find_one({"confirm_token": token}, {"_id": 0})
    if not sub:
        if redirect:
            return RedirectResponse(_public("/abo-bestaetigt?status=invalid"), status_code=303)
        return ConfirmResponse(
            status="invalid", message="Dieser Bestätigungslink ist ungültig oder abgelaufen."
        )

    already = sub.get("status") == "confirmed"
    if not already:
        await db.subscribers.update_one(
            {"email": sub["email"]},
            {"$set": {"status": "confirmed", "confirmed_at": _now_iso()}},
        )

    issue_sent = False
    issue = await _current_issue()
    if issue and not already:
        issue_sent, _ = await _deliver_issue(sub, issue)

    if redirect:
        state = "already" if already else ("sent" if issue_sent else "confirmed")
        return RedirectResponse(
            _public(f"/abo-bestaetigt?status={state}&email={sub['email']}"), status_code=303
        )
    return ConfirmResponse(
        status="already_confirmed" if already else "confirmed",
        message="Dein Abo war bereits bestätigt." if already else "Danke! Dein Abo ist bestätigt.",
        email=sub["email"],
        issue_sent=issue_sent,
    )


@router.get("/unsubscribe", response_model=ConfirmResponse)
async def unsubscribe(token: str = Query(...), redirect: bool = Query(True)):
    sub = await db.subscribers.find_one({"unsubscribe_token": token}, {"_id": 0})
    if not sub:
        if redirect:
            return RedirectResponse(_public("/abo-bestaetigt?status=invalid"), status_code=303)
        return ConfirmResponse(status="invalid", message="Dieser Abmeldelink ist ungültig.")
    await db.subscribers.update_one(
        {"email": sub["email"]}, {"$set": {"status": "unsubscribed"}}
    )
    if redirect:
        return RedirectResponse(
            _public(f"/abo-bestaetigt?status=unsubscribed&email={sub['email']}"), status_code=303
        )
    return ConfirmResponse(
        status="confirmed", message="Du wurdest abgemeldet.", email=sub["email"]
    )


@router.get("/subscribers/stats", response_model=SubscriberStats)
async def subscriber_stats():
    counts: Dict[str, int] = {}
    for status in ("confirmed", "pending", "unsubscribed"):
        counts[status] = await db.subscribers.count_documents({"status": status})
    recent_docs = (
        await db.subscribers.find({}, {"_id": 0, "confirm_token": 0, "unsubscribe_token": 0})
        .sort("created_at", -1)
        .to_list(8)
    )
    return SubscriberStats(
        confirmed=counts["confirmed"],
        pending=counts["pending"],
        unsubscribed=counts["unsubscribed"],
        total=sum(counts.values()),
        mail_configured=mailer.mail_configured(),
        sender=mailer.sender(),
        recent=[Subscriber(**d) for d in recent_docs],
    )


@router.post("/send-issue", response_model=SendIssueResponse)
async def send_issue(payload: SendIssueRequest):
    issue = await _current_issue()
    if not issue:
        raise HTTPException(status_code=404, detail="Es wurde noch keine Ausgabe erzeugt.")
    if not mailer.mail_configured():
        raise HTTPException(
            status_code=503,
            detail="RESEND_API_KEY ist nicht gesetzt — Mailversand ist noch nicht aktiv.",
        )

    if payload.test_email:
        targets: List[Dict[str, Any]] = [
            {"email": payload.test_email.strip().lower(), "unsubscribe_token": "test"}
        ]
    else:
        targets = await db.subscribers.find(
            {"status": "confirmed"}, {"_id": 0}
        ).to_list(2000)

    sent, failed, errors = 0, 0, []
    for target in targets:
        ok, err = await _deliver_issue(target, issue)
        if ok:
            sent += 1
        else:
            failed += 1
            if len(errors) < 5:
                errors.append(f"{target['email']}: {err[:140]}")
        await asyncio.sleep(0.6)  # stay inside Resend's rate limit

    return SendIssueResponse(
        sent=sent,
        failed=failed,
        skipped=0,
        test_mode=bool(payload.test_email),
        issue_title=issue.get("issue_title", ""),
        errors=errors,
    )
