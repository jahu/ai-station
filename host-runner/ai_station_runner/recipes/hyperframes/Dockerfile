FROM node:22-bookworm-slim AS sdk
WORKDIR /opt/sdk
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --omit=dev --no-audit --no-fund

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends chromium ffmpeg \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pydantic==2.13.5 pillow==12.3.0
COPY --from=sdk /usr/local/bin/node /usr/local/bin/node
COPY --from=sdk /opt/sdk /opt/sdk
COPY code/ /opt/ai-station/ai_station_runner/
ARG AI_STATION_MOTION_RECIPE
LABEL ai-station.motion.protocol="1" ai-station.motion.recipe="${AI_STATION_MOTION_RECIPE}"
ENV PYTHONPATH=/opt/ai-station PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
WORKDIR /work
ENTRYPOINT ["python", "-m", "ai_station_runner.motion_container"]
CMD []
