# BVM Newsletter Backend — selbst hosten

Dieses Paket ist der komplette Backend-Quellcode des Newsletter-Features.
Du brauchst **keinen** GitHub-Export und **kein** bezahltes Emergent-Abo, um es
zu betreiben — lade das ZIP herunter und deploye es bei einem Hoster deiner Wahl.

## Was drin ist

```
server.py               FastAPI-App, alle Routen unter /api
routers/                newsletter.py (PDF/Ausgabe), subscribers.py (Abo), integration.py
lib/                    sources.py (GitHub-JSON), editorial.py (KI), pdf_builder.py, mailer.py, db.py
models/                 Pydantic-Modelle
requirements.txt         Python-Abhängigkeiten
Dockerfile               lauffähiges Container-Image (inkl. Schriftarten für das PDF)
render.yaml              Render-Blueprint, füllt alle Variablen ab
.env.example             alle nötigen Umgebungsvariablen mit Erklärung
```

## Empfohlener Weg: Render (kostenlos, Region Frankfurt)

1. **Datenbank**: cloud.mongodb.com → kostenlosen **M0**-Cluster anlegen →
   *Connect* → *Drivers* → *Python* → Connection String kopieren.
   Unter *Network Access* `0.0.0.0/0` erlauben.
2. **Repo**: Entpacke das ZIP und lade den Inhalt in ein neues GitHub-Repo,
   z. B. `bvmevgiessen/bvm-newsletter-api`. Das geht komplett über die
   GitHub-Weboberfläche: *Add file → Upload files → Ordner hineinziehen*.
3. **Deploy**: render.com → *New* → *Blueprint* → dein Repo auswählen.
   Render liest `render.yaml` und fragt nach den geheimen Werten:
   `MONGO_URL`, `EMERGENT_LLM_KEY`, `RESEND_API_KEY`, `PUBLIC_BASE_URL`.
4. **Adresse übernehmen**: Render gibt dir z. B.
   `https://bvm-newsletter-api.onrender.com`. Diese Adresse
   - als `PUBLIC_BASE_URL` bei Render eintragen (damit Mail-Links stimmen),
   - als `VITE_NEWSLETTER_API` in deinem Website-Repo setzen,
   - als GitHub-Secret `NEWSLETTER_API` für die Action hinterlegen.

Eigene Subdomain (`newsletter.bvm-ev.de`): Render → Service → *Settings* →
*Custom Domains* → hinzufügen, dann den angezeigten CNAME bei deinem
DNS-Anbieter setzen. Danach `PUBLIC_BASE_URL` auf die Subdomain ändern.

## Alternativen

- **Railway**: New Project → Deploy from GitHub repo → erkennt den Dockerfile,
  Variablen aus `.env.example` manuell eintragen.
- **Fly.io**: `fly launch` im entpackten Ordner, dann `fly secrets set …`.
- **Lokal testen**: `pip install -r requirements.txt`, `.env.example` nach `.env`
  kopieren und ausfüllen, dann `uvicorn server:app --port 8001`.

## Wichtig

- `.env` ist **nicht** im ZIP (keine Schlüssel im Klartext). Nutze `.env.example`
  als Vorlage und trage die Werte beim Hoster als Umgebungsvariablen ein.
- Der Render-Free-Plan schläft nach ~15 Minuten Inaktivität ein. Der erste
  Aufruf danach dauert 30–50 Sekunden — für einen Quartals-Newsletter egal.
- `CORS_ORIGINS` muss deine Website-Adressen enthalten, sonst blockt der Browser
  die Anmeldung von bvm-ev.de aus.

## Testen, ob es läuft

```bash
curl https://DEINE-ADRESSE/api/
curl -X POST https://DEINE-ADRESSE/api/newsletter/build \
  -H 'Content-Type: application/json' -d '{"months":3}'
curl -o test.pdf https://DEINE-ADRESSE/api/newsletter/download
```
