# Optional CPU workload image; the control plane never receives Docker access.
FROM python:3.12-slim
RUN pip install --no-cache-dir openpyxl==3.1.5 matplotlib==3.11.2
COPY host-runner/ai_station_runner/python_container.py host-runner/ai_station_runner/python_protocol.py /opt/ai-station/
ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg MPLCONFIGDIR=/tmp/matplotlib
LABEL ai-station.python.protocol="1"
LABEL ai-station.python.data-exports="1"
LABEL ai-station.python.optional-outputs="1"
USER 1000:1000
WORKDIR /outputs
ENTRYPOINT ["python", "-u", "/opt/ai-station/python_container.py"]
