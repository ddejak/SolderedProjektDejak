FROM python:3.12-slim

# WeasyPrint 60+ renders via Pango/HarfBuzz (cairo was dropped in 53).
# Package names below are the Debian trixie ones used by python:3.12-slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    libjpeg62-turbo \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PORT=5000
EXPOSE 5000
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --timeout 120 app.main:app"]
