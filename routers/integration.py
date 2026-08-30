"""Serves the ready-to-paste integration files for the GitHub Pages repository.

The user's site lives in a separate repo (bvmevgiessen/bvm-ev-web), so instead of
needing a git push out of this workspace they can copy each file straight from the
browser. Files are read from /app/integration at request time.

/backend-bundle additionally zips the backend source (without secrets) so the
backend can be self-hosted without any platform export feature.
"""
from __future__ import annotations

import io
import os
import zipfile
from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/integration", tags=["integration"])

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTEGRATION_DIR = os.path.join(os.path.dirname(BACKEND_DIR), "integration")
DEPLOY_DIR = os.path.join(INTEGRATION_DIR, "deploy")

# Only these backend paths go into the bundle — never .env, caches or generated PDFs.
BUNDLE_INCLUDE = ["server.py", "lib", "models", "routers"]
BUNDLE_SKIP_DIRS = {"__pycache__", "tests", "generated", ".pytest_cache"}
BUNDLE_SKIP_FILES = {".env", "pytest.ini"}

# emergentintegrations is not on public PyPI — a plain `pip install -r` on Render or
# Railway would fail the whole build. The bundled requirements.txt therefore carries
# the extra index it lives on, and the editorial module already degrades to the
# template editorial if the import is unavailable.
EMERGENT_INDEX = "https://d33sy5i8bnduwe.cloudfront.net/simple/"


def _bundled_requirements() -> str:
    src = os.path.join(BACKEND_DIR, "requirements.txt")
    lines: List[str] = []
    with open(src, "r", encoding="utf-8") as fh:
        for line in fh.read().splitlines():
            if line.strip().lower().startswith("emergentintegrations"):
                lines.append(
                    "# emergentintegrations wird vom Extra-Index oben installiert "
                    "(nur für das KI-Editorial nötig)."
                )
                lines.append(line)
            else:
                lines.append(line)
    header = (
        "# Automatisch für das Selbst-Hosting angepasst.\n"
        f"--extra-index-url {EMERGENT_INDEX}\n"
        "#\n"
        "# Falls die Installation von emergentintegrations bei deinem Hoster scheitert:\n"
        "# einfach diese Zeile entfernen. Der Newsletter läuft weiter, das\n"
        "# 'Editorial der Redaktion' nutzt dann die redaktionelle Vorlage statt KI.\n"
    )
    return header + "\n".join(lines) + "\n"


class IntegrationFile(BaseModel):
    key: str
    filename: str
    target_path: str
    language: str
    title: str
    description: str
    replaces: str = ""
    content: str
    lines: int


class IntegrationBundle(BaseModel):
    api_base: str
    cors_open: bool
    files: List[IntegrationFile]
    backend_bundle_files: int = 0


CATALOG = [
    {
        "key": "component",
        "filename": "Newsletter.tsx",
        "target_path": "src/components/Newsletter.tsx",
        "language": "tsx",
        "title": "Newsletter-Komponente (Drop-in-Ersatz)",
        "description": (
            "Ersetzt deine bestehende Newsletter-Komponente. Behält dein Design und deine "
            "brand-Klassen, schickt die Anmeldung aber an die Newsletter-API (Double-Opt-In) "
            "und verlinkt das immer frische PDF."
        ),
        "replaces": "Formspree-POST auf https://formspree.io/f/xqejpyol",
    },
    {
        "key": "workflow",
        "filename": "newsletter-pdf.yml",
        "target_path": ".github/workflows/newsletter-pdf.yml",
        "language": "yaml",
        "title": "GitHub Action: PDF monatlich neu erzeugen",
        "description": (
            "Baut die Ausgabe zum Monatsanfang neu, committet public/newsletter-latest.pdf "
            "in dein Repo und kann die Ausgabe optional an alle Abonnenten senden."
        ),
        "replaces": "",
    },
    {
        "key": "readme",
        "filename": "README.md",
        "target_path": "NEWSLETTER-INTEGRATION.md",
        "language": "markdown",
        "title": "Anleitung & Checkliste",
        "description": (
            "Alle Schritte am Stück: Secrets, VITE_NEWSLETTER_API, Resend-Domain-Verify."
        ),
        "replaces": "",
    },
]


def _bundle_members() -> List[tuple[str, str]]:
    """(absolute_source_path, path_inside_zip) for every file in the bundle."""
    members: List[tuple[str, str]] = []
    for entry in BUNDLE_INCLUDE:
        src = os.path.join(BACKEND_DIR, entry)
        if os.path.isfile(src):
            members.append((src, entry))
        elif os.path.isdir(src):
            for root, dirs, filenames in os.walk(src):
                dirs[:] = [d for d in dirs if d not in BUNDLE_SKIP_DIRS]
                for name in filenames:
                    if name in BUNDLE_SKIP_FILES or name.endswith(".pyc"):
                        continue
                    abs_path = os.path.join(root, name)
                    members.append((abs_path, os.path.relpath(abs_path, BACKEND_DIR)))
    # Deployment scaffolding lives next to the backend inside the zip.
    for name in ("Dockerfile", "render.yaml", ".env.example", "README.md"):
        src = os.path.join(DEPLOY_DIR, name)
        if os.path.isfile(src):
            members.append((src, name))
    return members


@router.get("/files", response_model=IntegrationBundle)
async def integration_files():
    files: List[IntegrationFile] = []
    for entry in CATALOG:
        path = os.path.join(INTEGRATION_DIR, str(entry["filename"]))
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
        files.append(
            IntegrationFile(
                key=str(entry["key"]),
                filename=str(entry["filename"]),
                target_path=str(entry["target_path"]),
                language=str(entry["language"]),
                title=str(entry["title"]),
                description=str(entry["description"]),
                replaces=str(entry["replaces"]),
                content=content,
                lines=content.count("\n") + 1,
            )
        )
    if not files:
        raise HTTPException(status_code=404, detail="Keine Integrationsdateien gefunden.")
    return IntegrationBundle(
        api_base=os.environ.get("PUBLIC_BASE_URL", "").rstrip("/"),
        cors_open=os.environ.get("CORS_ORIGINS", "*").strip() == "*",
        files=files,
        backend_bundle_files=len(_bundle_members()) + 1,
    )


@router.get("/backend-bundle")
async def backend_bundle():
    """Zip of the backend source + Dockerfile/render.yaml, secrets excluded.

    Lets the Verein self-host the backend without any platform export feature.
    """
    members = _bundle_members()
    if not members:
        raise HTTPException(status_code=404, detail="Backend-Quellcode nicht gefunden.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for abs_path, rel_path in members:
            zf.write(abs_path, arcname=f"bvm-newsletter-api/{rel_path}")
        zf.writestr("bvm-newsletter-api/requirements.txt", _bundled_requirements())
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="bvm-newsletter-api.zip"'
        },
    )
