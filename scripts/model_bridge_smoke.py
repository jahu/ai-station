"""Docker → private Runner socket → loopback provider acceptance.

Default uses a fake local provider. --real requires explicit local-LLM opt-in.
Only the disposable Compose project created here is started/stopped.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true")
    args = parser.parse_args()
    if args.real and os.environ.get("AI_STATION_REAL_LOCAL_LLM_TESTS") != "1":
        raise SystemExit("Set AI_STATION_REAL_LOCAL_LLM_TESTS=1 for actual inference")
    stop = threading.Event()
    silent_started = threading.Event()

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"data":[{"id":"fake-bridge"}]}')

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.flush()
            if body["messages"][-1]["content"] == "Wait silently":
                silent_started.set()
                stop.wait(20)
                return
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"AI Station bridge OK."}}]}\n\n')
            self.wfile.write(b"data: [DONE]\n\n")

    provider = None
    if not args.real:
        provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        threading.Thread(target=provider.serve_forever, daemon=True).start()
        endpoint = f"http://127.0.0.1:{provider.server_port}/v1"
        model = "fake-bridge"
    else:
        endpoint = os.environ["AI_STATION_LLM_BASE_URL"]
        model = os.environ["AI_STATION_LLM_MODEL"]
    with tempfile.TemporaryDirectory(prefix="ai-station-bridge-") as temporary:
        root = Path(temporary)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {
            **os.environ,
            "COMPOSE_PROJECT_NAME": "ai-station-bridge-" + uuid4().hex[:8],
            "AI_STATION_DATA_HOST_PATH": str(root / "data"),
            "AI_STATION_RUNNER_SOCKET": str(root / "runner/runner.sock"),
            "AI_STATION_PORT": str(port),
            "AI_STATION_LLM_BASE_URL": endpoint,
            "AI_STATION_LLM_CONTAINER_BASE_URL": "http://127.0.0.1:1/v1",
            "AI_STATION_LLM_TRANSPORT": "runner",
            "AI_STATION_LLM_MODEL": model,
            "AI_STATION_LLM_API_KEY": "",
        }
        with (root / "launcher.log").open("w+") as log:
            launcher = subprocess.Popen(
                [sys.executable, "scripts/launch.py", "--no-build"], cwd=ROOT, env=env, stdout=log, stderr=log
            )
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15, trust_env=False) as api:
                    deadline = time.monotonic() + 120
                    while time.monotonic() < deadline:
                        if launcher.poll() is not None:
                            raise RuntimeError("Launcher exited early")
                        try:
                            if api.get("/api/health").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.2)
                    else:
                        raise RuntimeError("Control plane did not become healthy")
                    discovered = api.get("/api/chat/provider").json()
                    assert discovered["status"] == "available", discovered
                    assert model in discovered["models"], discovered
                    assert discovered["endpoint"] == endpoint
                    conversation = api.post(
                        "/api/chat/conversations",
                        json={
                            "model": model,
                            "title": "Bridge acceptance",
                            "temperature": 0,
                            "max_tokens": 512,
                        },
                    )
                    conversation.raise_for_status()
                    conversation_id = conversation.json()["id"]

                    def run_message(content):
                        response = api.post(
                            f"/api/chat/conversations/{conversation_id}/messages", json={"content": content}
                        )
                        response.raise_for_status()
                        return response.json()["id"]

                    def finished(run_id, timeout=120):
                        deadline = time.monotonic() + timeout
                        while time.monotonic() < deadline:
                            row = api.get(f"/api/runs/{run_id}").json()
                            if row["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
                                return row
                            time.sleep(0.25)
                        raise RuntimeError("Run did not finish")

                    run_id = run_message("Reply exactly: AI Station bridge OK. /no_think")
                    result = finished(run_id)
                    assert result["status"] == "succeeded", result
                    text = api.get(f"/api/chat/conversations/{conversation_id}").json()["messages"][-1][
                        "content"
                    ]
                    assert "bridge OK" in text, text
                    print("PASS: Docker worker → UDS → host loopback model; response:", text, flush=True)
                    if not args.real:
                        run_id = run_message("Wait silently")
                        assert silent_started.wait(20)
                        api.post(f"/api/runs/{run_id}/cancel").raise_for_status()
                        assert finished(run_id, timeout=10)["status"] == "canceled"
                        print("PASS: silent upstream cancellation through the private bridge", flush=True)
            except Exception:
                log.flush()
                print(Path(log.name).read_text()[-8000:])
                raise
            finally:
                stop.set()
                launcher.terminate()
                launcher.wait(timeout=45)
                if provider:
                    provider.shutdown()
                    provider.server_close()


if __name__ == "__main__":
    main()
