"""Native process selection and independently qualified typed API operations."""

import sys
from pathlib import Path

from fastapi import HTTPException, Request

from ai_station_runner.processes import ProcessManager

# Native ownership/Stop is qualified on ARM and Intel. This does not qualify
# Linux cgroups, CUDA/container/media recipes or their model preparation on Mac.
# Match the registered route template, never a caller-controlled prefix. Future
# routers remain unavailable until deliberately admitted with platform evidence.
_DARWIN_OPERATIONS = frozenset(
    {
        ("GET", "/health"),
        ("GET", "/v1/hardware"),
        ("GET", "/v1/process/{run_id}"),
        ("POST", "/v1/process/cancel"),
        ("GET", "/v1/setup/native-llama"),
        ("POST", "/v1/setup/native-llama/prepare"),
        ("GET", "/v1/setup/native-llama/{identity}"),
        ("POST", "/v1/setup/native-llama/{identity}/cancel"),
        ("POST", "/v1/setup/native-llama/{identity}/adopt"),
        ("POST", "/v1/llama/load"),
        ("GET", "/v1/llama/{instance_id}"),
        ("POST", "/v1/llama/{instance_id}/stop"),
        ("POST", "/v1/llama/{instance_id}/chat/completions"),
        ("POST", "/v1/llama/{instance_id}/coding/completions"),
    }
)


def create_process_manager(data_dir: Path, grace_seconds: float = 3.0) -> ProcessManager:
    if sys.platform == "linux":
        return ProcessManager(data_dir, grace_seconds)
    if sys.platform == "darwin":
        from ai_station_runner.darwin_processes import DarwinProcessManager

        return DarwinProcessManager(data_dir, grace_seconds)
    # Refuse before constructing storage or scheduling recovered deadlines.
    raise RuntimeError("Managed host processes require a qualified Linux or macOS adapter")


def require_qualified_operation(request: Request) -> None:
    if sys.platform == "linux":
        return
    route = request.scope["route"]
    if sys.platform == "darwin" and (request.method, route.path) in _DARWIN_OPERATIONS:
        return
    raise HTTPException(503, "This Host Runner operation is not yet qualified on this platform")
