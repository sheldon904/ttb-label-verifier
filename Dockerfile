# Single container, no egress. Tesseract is the only system dependency; the
# English traineddata ships with the Debian package, so the image is complete
# at build time and never fetches anything at run time (Marcus Williams's
# firewall would block it if it tried).
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY fixtures/labels ./fixtures/labels
COPY fixtures/records ./fixtures/records

# Nothing is written to disk by the application; run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

ENV LABEL_EXTRACTOR=ocr \
    MAX_BATCH_CONCURRENCY=4 \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8000'))"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
