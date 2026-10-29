# Alternative Render runtime.
#
# The native Python runtime is the primary path (see render.yaml). Use this
# Dockerfile only if you need to control the base image exactly, or if the
# native runtime stops supporting the Python version you need.
#
#   Render -> New -> Web Service -> Runtime: Docker
#   Dockerfile Path: ./Dockerfile
#   Docker Context: .

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so the layer caches across code changes.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Migrate, then serve. `exec` hands PID 1 to uvicorn so Render's health
# checks and its stop signal reach the server directly.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --proxy-headers --forwarded-allow-ips=*"]
