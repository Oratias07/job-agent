FROM python:3.12-slim

# ── System dependencies ───────────────────────────────────────────────────────
# WeasyPrint needs the Pango/GDK stack (GTK text rendering)
# Playwright Chromium needs its own set of shared libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    # WeasyPrint / Pango
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    libffi-dev \
    shared-mime-info \
    # Playwright Chromium
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    # General
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python dependencies ───────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright's bundled Chromium (no system Chrome needed)
RUN playwright install chromium --with-deps

# ── Application code ──────────────────────────────────────────────────────────
COPY . .

# ── Runtime ───────────────────────────────────────────────────────────────────
CMD ["python", "bot_listener.py"]
