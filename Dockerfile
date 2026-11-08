# Pinned to bookworm (not the unqualified "slim" tag, which now resolves to
# Debian trixie): Playwright 1.49.1's `--with-deps` installer references
# apt packages (ttf-ubuntu-font-family, ttf-unifont) that trixie renamed/
# dropped, so `playwright install --with-deps chromium` fails there.
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY app ./app
COPY static ./static

RUN mkdir -p /srv/data

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
