# Separate optional workload image. Never used as a control-plane service.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends chromium fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir playwright==1.63.0
COPY host-runner/ai_station_runner/browser_renderer.py /opt/ai-station/browser_renderer.py
ENV HOME=/tmp PYTHONUNBUFFERED=1
LABEL ai-station.browser.protocol="1"
USER 1000:1000
WORKDIR /tmp
ENTRYPOINT ["python", "-u", "/opt/ai-station/browser_renderer.py"]
