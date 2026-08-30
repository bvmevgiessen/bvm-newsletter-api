"""Resend-backed mailing for the BVM newsletter.

The Resend SDK is synchronous, so every call goes through asyncio.to_thread to
keep the FastAPI event loop free. Email HTML uses tables + inline CSS only.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

TERRACOTTA = "#c0431d"
FOREST = "#1e3d34"
AMBER = "#d97706"
CREAM = "#faf8f5"


def sender() -> str:
    name = os.environ.get("SENDER_NAME", "BVM e.V. Gießen")
    addr = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
    return f"{name} <{addr}>"


def public_base() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")


def mail_configured() -> bool:
    return bool(os.environ.get("RESEND_API_KEY", "").strip())


def _esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _shell(inner: str, preheader: str) -> str:
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background-color:{CREAM};">
<div style="display:none;max-height:0;overflow:hidden;">{_esc(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background-color:{CREAM};padding:24px 12px;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
           style="width:600px;max-width:600px;background-color:#ffffff;border-radius:14px;overflow:hidden;
                  font-family:Helvetica,Arial,sans-serif;">
      {inner}
    </table>
  </td></tr>
</table>
</body></html>"""


def _header(title: str, subtitle: str) -> str:
    return f"""
<tr><td style="background-color:{TERRACOTTA};padding:32px 32px 26px 32px;">
  <p style="margin:0 0 10px 0;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#ffe3d2;">
    BVM e.V. Gie&szlig;en &middot; Quartals-Newsletter</p>
  <h1 style="margin:0;font-family:Georgia,serif;font-size:28px;line-height:34px;color:#ffffff;">
    {_esc(title)}</h1>
  <p style="margin:8px 0 0 0;font-family:Georgia,serif;font-style:italic;font-size:15px;color:#fde7d9;">
    {_esc(subtitle)}</p>
</td></tr>
<tr><td style="height:5px;background-color:{FOREST};font-size:0;line-height:0;">&nbsp;</td></tr>"""


def _footer(unsubscribe_url: str = "") -> str:
    unsub = (
        f'<p style="margin:12px 0 0 0;font-size:11px;color:#9fc3b3;">'
        f'Newsletter nicht mehr erhalten? '
        f'<a href="{unsubscribe_url}" style="color:#ffc78f;">Hier abmelden</a>.</p>'
        if unsubscribe_url
        else ""
    )
    return f"""
<tr><td style="background-color:{FOREST};padding:28px 32px;">
  <p style="margin:0;font-family:Georgia,serif;font-size:17px;color:#ffffff;">BVM e.V. Gie&szlig;en</p>
  <p style="margin:8px 0 0 0;font-size:13px;line-height:20px;color:#cfe3d8;">
    Bund der Vereine f&uuml;r Multikulturelles Miteinander<br>
    Gie&szlig;en, Hessen &middot;
    <a href="mailto:bvmevgiessen@gmail.com" style="color:#ffc78f;text-decoration:none;">bvmevgiessen@gmail.com</a><br>
    <a href="https://bvm-ev.de" style="color:#ffc78f;text-decoration:none;">bvm-ev.de</a>
  </p>
  {unsub}
</td></tr>"""


def _button(label: str, url: str, color: str = TERRACOTTA) -> str:
    return f"""
<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0;">
  <tr><td style="background-color:{color};border-radius:9px;">
    <a href="{url}" style="display:inline-block;padding:14px 26px;font-size:15px;font-weight:bold;
       color:#ffffff;text-decoration:none;">{_esc(label)}</a>
  </td></tr>
</table>"""


def confirmation_html(confirm_url: str) -> str:
    inner = (
        _header("Nur noch ein Klick!", "Bitte bestätige deine Anmeldung")
        + f"""
<tr><td style="padding:32px;">
  <p style="margin:0 0 16px 0;font-size:15px;line-height:24px;color:#1c1b1f;">
    Hallo und herzlich willkommen!</p>
  <p style="margin:0 0 16px 0;font-size:15px;line-height:24px;color:#44403c;">
    Du m&ouml;chtest unseren Quartals-Newsletter erhalten – wunderbar, wir freuen uns sehr.
    Aus Datenschutzgr&uuml;nden (Double-Opt-In) brauchen wir noch deine Best&auml;tigung.</p>
  {_button("Anmeldung jetzt bestätigen", confirm_url)}
  <p style="margin:16px 0 0 0;font-size:13px;line-height:20px;color:#78716c;">
    Direkt danach schicken wir dir die <strong>aktuelle Ausgabe</strong> mit allen Events und
    Blogbeitr&auml;gen der letzten drei Monate – inklusive PDF zum Aufbewahren.</p>
  <p style="margin:18px 0 0 0;font-size:12px;line-height:18px;color:#a8a29e;">
    Du hast dich nicht angemeldet? Dann ignoriere diese E-Mail einfach – ohne Best&auml;tigung
    speichern wir dauerhaft nichts und senden dir nichts zu.
  </p>
</td></tr>"""
        + _footer()
    )
    return _shell(inner, "Bitte bestätige deine Newsletter-Anmeldung bei BVM e.V. Gießen")


def _item_rows(items: List[Dict[str, Any]], accent: str, limit: int = 4) -> str:
    from lib.pdf_builder import de_date

    rows = []
    for item in items[:limit]:
        meta = de_date(item.get("date", ""))
        if item.get("location"):
            meta += f" &middot; {_esc(item['location'])}"
        elif item.get("partner_name"):
            meta += f" &middot; {_esc(item['partner_name'])}"
        img = item.get("image", "")
        img_cell = (
            f'<img src="{_esc(img)}" width="120" alt="" '
            f'style="display:block;width:120px;height:84px;object-fit:cover;border-radius:8px;">'
            if img
            else ""
        )
        rows.append(
            f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="margin:0 0 16px 0;border-left:4px solid {accent};background-color:#ffffff;">
  <tr>
    <td width="132" valign="top" style="padding:10px 12px 10px 14px;">{img_cell}</td>
    <td valign="top" style="padding:10px 6px 10px 0;">
      <p style="margin:0 0 4px 0;font-size:12px;font-weight:bold;color:{accent};">{meta}</p>
      <p style="margin:0 0 6px 0;font-family:Georgia,serif;font-size:16px;line-height:21px;color:#1c1b1f;">
        <strong>{_esc(item.get('title', ''))}</strong></p>
      <p style="margin:0;font-size:13px;line-height:19px;color:#57534e;">
        {_esc((item.get('summary') or '')[:190])}</p>
    </td>
  </tr>
</table>"""
        )
    return "".join(rows)


def _section_title(number: str, title: str, accent: str) -> str:
    return f"""
<p style="margin:26px 0 14px 0;font-size:12px;letter-spacing:1.6px;text-transform:uppercase;
          color:{accent};border-bottom:2px solid {accent};padding-bottom:7px;">
  {number} &nbsp; {_esc(title)}</p>"""


def issue_html(newsletter: Dict[str, Any], unsubscribe_url: str, download_url: str) -> str:
    paras = [p.strip() for p in newsletter.get("editorial", "").split("\n") if p.strip()][:2]
    editorial = "".join(
        f'<p style="margin:0 0 12px 0;font-family:Georgia,serif;font-size:15px;'
        f'line-height:24px;color:#292524;">{_esc(p)}</p>'
        for p in paras
    )
    events = newsletter.get("events", [])
    blogs = newsletter.get("blogs", [])
    upcoming = newsletter.get("upcoming", [])

    upcoming_html = ""
    if upcoming:
        from lib.pdf_builder import de_date

        lis = "".join(
            f'<li style="margin:0 0 7px 0;font-size:14px;line-height:20px;color:#292524;">'
            f'<strong>{_esc(de_date(u.get("date", "")))}</strong> — {_esc(u.get("title", ""))}'
            f'{(" &middot; " + _esc(u["location"])) if u.get("location") else ""}</li>'
            for u in upcoming
        )
        upcoming_html = (
            _section_title("04", "Was kommt als Nächstes?", TERRACOTTA)
            + f'<p style="margin:0 0 12px 0;font-size:14px;line-height:21px;color:#57534e;">'
            f'{_esc(newsletter.get("teaser_intro", ""))}</p>'
            f'<ul style="margin:0;padding-left:20px;">{lis}</ul>'
        )

    inner = (
        _header(newsletter.get("issue_title", "Newsletter"), f"Ausgabe {newsletter.get('issue_period', '')}")
        + f"""
<tr><td style="padding:30px 32px 34px 32px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background-color:#fff8f0;border-left:4px solid {AMBER};border-radius:8px;">
    <tr><td style="padding:20px 22px;">
      <p style="margin:0 0 10px 0;font-size:12px;letter-spacing:1.6px;text-transform:uppercase;color:{TERRACOTTA};">
        01 &nbsp; Editorial der Redaktion</p>
      {editorial}
      <p style="margin:6px 0 0 0;font-family:Georgia,serif;font-style:italic;font-size:14px;color:{TERRACOTTA};">
        Herzlich, Ihre Redaktion</p>
    </td></tr>
  </table>

  {_section_title("02", f"Unsere Events ({len(events)})", FOREST)}
  {_item_rows(events, TERRACOTTA) or '<p style="font-size:14px;color:#78716c;">Keine Veranstaltungen in diesem Zeitraum.</p>'}

  {_section_title("03", f"Stimmen aus dem Blog ({len(blogs)})", AMBER)}
  {_item_rows(blogs, AMBER) or '<p style="font-size:14px;color:#78716c;">Keine Blogbeiträge in diesem Zeitraum.</p>'}

  {upcoming_html}

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         style="margin:30px 0 0 0;background-color:{CREAM};border-radius:10px;">
    <tr><td align="center" style="padding:24px;">
      <p style="margin:0 0 6px 0;font-family:Georgia,serif;font-size:18px;color:{FOREST};">
        Die komplette Ausgabe als PDF</p>
      <p style="margin:0 0 14px 0;font-size:13px;color:#57534e;">
        A4 in Vollfarbe &middot; {newsletter.get('pdf_pages', 0)} Seiten &middot; auch im Anhang dieser E-Mail</p>
      {_button("PDF ansehen", download_url, AMBER)}
    </td></tr>
  </table>
</td></tr>"""
        + _footer(unsubscribe_url)
    )
    return _shell(
        inner,
        f"{newsletter.get('issue_title', '')} — {len(events)} Events und {len(blogs)} Blogbeiträge",
    )


async def send_mail(
    to: str,
    subject: str,
    html: str,
    pdf_path: str | None = None,
    pdf_name: str = "bvm-newsletter.pdf",
) -> Tuple[bool, str]:
    """Send one email. Returns (ok, error_message)."""
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        return False, "RESEND_API_KEY ist nicht gesetzt."

    import resend

    resend.api_key = api_key
    params: Dict[str, Any] = {
        "from": sender(),
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if pdf_path and os.path.exists(pdf_path):
        with open(pdf_path, "rb") as fh:
            params["attachments"] = [
                {
                    "filename": pdf_name,
                    "content": base64.b64encode(fh.read()).decode("ascii"),
                }
            ]
    try:
        result = await asyncio.to_thread(resend.Emails.send, params)
        return True, str(result.get("id", "")) if isinstance(result, dict) else ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("Resend send to %s failed: %s", to, exc)
        return False, str(exc)
