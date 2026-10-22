# Optional internal workload. Build from the already installed project browser image.
# No control-plane service or published host port is added.
ARG BROWSER_BASE=ai-station-browser:local
FROM ${BROWSER_BASE}
COPY host-runner/ai_station_runner/site_preview_protocol.py /opt/ai-station/site_preview_protocol.py
COPY host-runner/ai_station_runner/site_preview_renderer.py /opt/ai-station/site_preview_renderer.py
LABEL ai-station.site-preview.protocol="2"
ENTRYPOINT ["python", "-u", "/opt/ai-station/site_preview_renderer.py"]
