"""AI-written 'Editorial der Redaktion' (German) via the Emergent LLM key."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# The Emergent LLM key allows one in-flight completion at a time; serialise calls
# so two editors clicking "regenerate" don't knock each other into the fallback.
_LLM_LOCK = asyncio.Lock()

SYSTEM_MESSAGE = (
    "Du bist die Chefredakteurin des Quartals-Newsletters von BVM e.V. Gießen "
    "(Bund der Vereine für Multikulturelles Miteinander, Mittelhessen). "
    "Du schreibst ausschließlich auf Deutsch: lebendig, herzlich, modern und einladend. "
    "Du feierst Gemeinschaftsgeist, Vielfalt und geteilte Erlebnisse. "
    "Kurze Absätze, warme Sprache, keine Floskeln, keine Aufzählungen, keine Überschrift, "
    "keine Anrede-Signatur. Genau zwei Absätze, getrennt durch eine Leerzeile, "
    "insgesamt 130 bis 190 Wörter."
)


def _digest(events: List[Dict], blogs: List[Dict], upcoming: List[Dict]) -> str:
    lines: List[str] = []
    lines.append("EVENTS DER LETZTEN DREI MONATE:")
    for e in events:
        bits = [f"- {e['title']} ({e['date'][:10]})"]
        if e.get("location"):
            bits.append(f"Ort: {e['location']}")
        if e.get("summary"):
            bits.append(e["summary"])
        if e.get("highlights"):
            bits.append("Highlights: " + ", ".join(e["highlights"][:4]))
        lines.append(" | ".join(bits))
    lines.append("")
    lines.append("BLOGBEITRÄGE:")
    for b in blogs:
        bits = [f"- {b['title']} ({b['date'][:10]})"]
        if b.get("partner_name"):
            bits.append(f"Partnerverein: {b['partner_name']}")
        if b.get("summary"):
            bits.append(b["summary"])
        lines.append(" | ".join(bits))
    if upcoming:
        lines.append("")
        lines.append("KOMMT ALS NÄCHSTES:")
        for u in upcoming:
            lines.append(f"- {u['title']} ({u['date'][:10]}) {u.get('location', '')}")
    return "\n".join(lines)


def fallback_editorial(events: List[Dict], blogs: List[Dict], period: str) -> str:
    titles = [e["title"] for e in events[:3]] or ["unseren Begegnungen"]
    joined = ", ".join(titles)
    return (
        f"Liebe Leserinnen und Leser, was für ein Vierteljahr! Zwischen {period} haben wir "
        f"{len(events)} Veranstaltungen und {len(blogs)} Blogbeiträge miteinander erlebt – "
        f"unter anderem {joined}. Jedes Treffen war eine Einladung: Setz dich dazu, erzähl uns "
        "deine Geschichte, iss mit uns, denk mit uns.\n\n"
        "Genau das macht BVM e.V. aus. Vielfalt ist bei uns kein Programmpunkt, sondern der "
        "Alltag – herzlich, neugierig und offen für alle. Blättere weiter und erlebe diese "
        "Monate noch einmal mit uns. Wir freuen uns auf alles, was als Nächstes kommt."
    )


async def generate_editorial(
    events: List[Dict],
    blogs: List[Dict],
    upcoming: List[Dict],
    period: str,
    tone_hint: str = "",
) -> Tuple[str, str]:
    """Return (editorial_text, source) where source is 'ai' or 'fallback'."""
    api_key = os.environ.get("EMERGENT_LLM_KEY", "").strip()
    if not api_key:
        return fallback_editorial(events, blogs, period), "fallback"

    from emergentintegrations.llm.chat import LlmChat, UserMessage

    prompt = (
        f"Schreibe das 'Editorial der Redaktion' für die Newsletter-Ausgabe {period}.\n"
        f"Nutze ausschließlich die folgenden echten Inhalte unserer Vereins-Website.\n"
        f"Nenne mindestens zwei konkrete Veranstaltungen oder Beiträge namentlich.\n"
        f"{('Zusätzlicher Wunsch der Redaktion: ' + tone_hint) if tone_hint else ''}\n\n"
        f"{_digest(events, blogs, upcoming)}"
    )

    async with _LLM_LOCK:
        for attempt in range(2):
            try:
                chat = LlmChat(
                    api_key=api_key,
                    session_id=f"bvm-editorial-{period}-{attempt}",
                    system_message=SYSTEM_MESSAGE,
                ).with_model("anthropic", "claude-sonnet-4-6")
                text = await chat.send_message(UserMessage(text=prompt))
                text = (text or "").strip()
                # The model occasionally answers in Markdown; the PDF and the web
                # reader both render plain text, so drop emphasis markers.
                text = text.replace("**", "").replace("##", "").strip()
                if len(text) < 80:
                    raise ValueError("editorial too short")
                return text, "ai"
            except Exception as exc:  # noqa: BLE001 - never let the build fail on the LLM
                logger.warning("AI editorial attempt %s failed: %s", attempt + 1, exc)
                if attempt == 0:
                    await asyncio.sleep(3)

    return fallback_editorial(events, blogs, period), "fallback"
