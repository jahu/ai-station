FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run typecheck && npm run build

FROM python:3.12-slim AS dependencies
WORKDIR /build
COPY requirements.lock ./
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements.lock

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONPATH=/app/backend PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    AI_STATION_DATA_DIR=/data AI_STATION_FRONTEND_DIST=/app/frontend
WORKDIR /app
LABEL org.opencontainers.image.licenses="PolyForm-Noncommercial-1.0.0"
COPY LICENSE NOTICE COMMERCIAL.md /app/legal/
COPY --from=dependencies /opt/venv /opt/venv
COPY backend/ /app/backend/
# Only pure metadata/admission modules are shared; no native Runner API or launcher.
COPY host-runner/ai_station_runner/torch_state_data.py \
     host-runner/ai_station_runner/torch_state_zip.py \
     host-runner/ai_station_runner/station_release_metadata.py /app/backend/ai_station_runner/
COPY scripts/desktop_connection.py scripts/desktop_link.py scripts/desktop_control.py scripts/desktop_versions.py /app/desktop/
COPY scripts/station_recovery/__init__.py scripts/station_recovery/storage.py scripts/station_recovery/accounts.py /app/desktop/station_recovery/
COPY --from=frontend /build/dist /app/frontend/
USER 1000:1000
EXPOSE 8765
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8765"]
