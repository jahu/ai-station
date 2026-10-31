"""HTTP client for the Host Runner Unix socket."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings


class RunnerUnavailable(Exception):
    pass


class RunnerError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class RunnerClient:
    def __init__(self, socket_path: str | None = None, timeout: float = 30.0):
        self.socket_path = socket_path or get_settings().runner_socket
        self.timeout = timeout

    def _client(self) -> httpx.Client:
        transport = httpx.HTTPTransport(uds=self.socket_path)
        return httpx.Client(transport=transport, base_url="http://runner", timeout=self.timeout)

    def request(self, method: str, path: str, json: dict | None = None) -> Any:
        try:
            with self._client() as client:
                response = client.request(method, path, json=json)
        except (httpx.HTTPError, FileNotFoundError, OSError) as exc:
            raise RunnerUnavailable(str(exc)) from exc
        if response.status_code >= 400:
            detail = response.text
            try:
                body = response.json()
                detail = str(body.get("detail", detail))
            except Exception:
                pass
            raise RunnerError(response.status_code, detail)
        if response.content:
            return response.json()
        return {}

    def runtime_setup_catalog(self) -> dict:
        return self.request("GET", "/v1/setup/runtimes")

    def prepare_runtime(self, payload: dict) -> dict:
        return self.request("POST", "/v1/setup/runtimes/prepare", payload)

    def inspect_runtime_preparation(
        self, identity: str, *, stdout_offset: int = 0, stderr_offset: int = 0
    ) -> dict:
        return self.request(
            "GET",
            f"/v1/setup/runtimes/{identity}?stdout_offset={stdout_offset}&stderr_offset={stderr_offset}",
        )

    def cancel_runtime_preparation(self, identity: str, payload: dict) -> dict:
        return self.request("POST", f"/v1/setup/runtimes/{identity}/cancel", payload)

    def load_llama(self, payload: dict) -> dict:
        return self.request("POST", "/v1/llama/load", payload)

    def inspect_llama(self, instance_id: str) -> dict:
        return self.request("GET", f"/v1/llama/{instance_id}")

    def stop_llama(self, instance_id: str) -> dict:
        return self.request("POST", f"/v1/llama/{instance_id}/stop", {"permissions": ["manage_models"]})

    def health(self) -> dict:
        return self.request("GET", "/health")

    def hardware(self) -> dict:
        return self.request("GET", "/v1/hardware")

    def gpu_processes(self) -> dict:
        return self.request("GET", "/v1/gpu-processes")

    def observe_runtimes(self) -> dict:
        return self.request("GET", "/v1/runtimes/observe")

    def verify_model(self, payload: dict) -> dict:
        return self.request("POST", "/v1/models/verify", payload)

    def diagnostics(self) -> dict:
        return self.request("GET", "/v1/diagnostics")

    def inspect_station_image(self) -> dict:
        return self.request("GET", "/v1/station-image")

    def scan_models(self) -> dict:
        return self.request("POST", "/v1/models/scan", {})

    def start_photo(self, payload: dict) -> dict:
        return self.request("POST", "/v1/runs/photo", payload)

    def start_krea_image(self, payload: dict) -> dict:
        return self.request("POST", "/v1/runs/krea2", payload)

    def start_coding(self, payload: dict) -> dict:
        return self.request("POST", "/v1/runs/coding", payload)

    def inspect_process(
        self, run_id: str, *, stdout_offset: int | None = None, stderr_offset: int | None = None
    ) -> dict:
        query = ""
        if stdout_offset is not None and stderr_offset is not None:
            query = f"?stdout_offset={stdout_offset}&stderr_offset={stderr_offset}"
        return self.request("GET", f"/v1/process/{run_id}{query}")

    def cancel_process(self, run_id: str) -> dict:
        return self.request("POST", "/v1/process/cancel", {"run_id": run_id})

    def validate_project(self, repo_path: str) -> dict:
        return self.request("POST", "/v1/git/validate", {"repo_path": repo_path})

    def git_status(self, repo_path: str) -> dict:
        return self.request("POST", "/v1/git/status", {"repo_path": repo_path})

    def git_diff(self, repo_path: str, base: str | None = None) -> dict:
        return self.request("POST", "/v1/git/diff", {"repo_path": repo_path, "base": base})

    def create_worktree(self, payload: dict) -> dict:
        return self.request("POST", "/v1/git/worktree", payload)

    def prepare_worktree(self, payload: dict) -> dict:
        return self.request("POST", "/v1/runs/worktree", payload)

    def start_cursor_proposal(self, payload: dict) -> dict:
        return self.request("POST", "/v1/runs/cursor-proposal", payload)

    def cursor_proposal_report(self, run_id: str) -> dict:
        return self.request("GET", f"/v1/cursor-proposal/{run_id}")

    def start_local_proposal(self, payload: dict) -> dict:
        return self.request("POST", "/v1/runs/local-coding-proposal", payload)

    def local_proposal_report(self, run_id: str) -> dict:
        return self.request("GET", f"/v1/local-coding-proposal/{run_id}")

    def start_validation(self, payload: dict) -> dict:
        return self.request("POST", "/v1/runs/validation", payload)

    def validation_report(self, run_id: str) -> dict:
        return self.request("GET", f"/v1/validation/{run_id}")

    def inspect_worktree(self, run_id: str) -> dict:
        return self.request("GET", f"/v1/worktrees/{run_id}")

    def remove_worktree(self, payload: dict) -> dict:
        return self.request("POST", "/v1/git/worktree/remove", payload)

    def git_commit(self, payload: dict) -> dict:
        return self.request("POST", "/v1/git/commit", payload)

    def create_pr(self, payload: dict) -> dict:
        return self.request("POST", "/v1/git/pr", payload)

    def read_file(self, payload: dict) -> dict:
        return self.request("POST", "/v1/fs/read", payload)

    def write_file(self, payload: dict) -> dict:
        return self.request("POST", "/v1/fs/write", payload)

    def list_dir(self, payload: dict) -> dict:
        return self.request("POST", "/v1/fs/list", payload)

    def search_files(self, payload: dict) -> dict:
        return self.request("POST", "/v1/fs/search", payload)

    def apply_patch(self, payload: dict) -> dict:
        return self.request("POST", "/v1/git/apply", payload)

    def run_project_command(self, payload: dict) -> dict:
        return self.request("POST", "/v1/project/command", payload)
