# --- BVM Newsletter Backend ------------------------------------------------
# Works on Render, Railway, Fly.io, or any Docker host.
FROM python:3.11-slim

# Liberation fonts are used by the PDF generator for headings/body text.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hosts inject $PORT; default to 8001 for local runs.
ENV PORT=8001
EXPOSE 8001

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8001}"]
