FROM python:3.11-slim

# Non-root user (Cloud Run security baseline)
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Install dependencies before copying source so this layer caches on pip changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code.
COPY app/ ./app/
COPY scripts/ ./scripts/

# Cloud Run injects PORT; default to 8080 for local docker run.
ENV PORT=8080

USER appuser

ENTRYPOINT ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port $PORT"]
