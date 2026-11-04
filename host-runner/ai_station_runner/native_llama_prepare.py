"""Fixed native llama.cpp SDK preparation through the owned environment lifecycle."""

import platform
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_station_runner import runtime_install
from ai_station_runner.config import get_settings
from ai_station_runner.darwin_llama_environment import NAMESPACE, PROFILES, Environment
from ai_station_runner.environment_files import read_json
from ai_station_runner.environment_prepare import OwnedEnvironmentPreparation
from ai_station_runner.speech_environment import fingerprint
from ai_station_runner.telemetry import collect
from ai_station_runner.windows_storage import disk_usage

Profile = Literal["llamacpp-native-darwin-arm64-b12032-v2", "llamacpp-native-darwin-x86_64-b12032-v2"]
PERMISSIONS = {"manage_models", "network_read", "workspace_write"}
router = APIRouter(prefix="/v1/setup/native-llama", tags=["native llama.cpp SDK preparation"])


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: Profile
    permissions: list[Literal["manage_models", "network_read", "workspace_write"]] = Field(max_length=3)


class Preparation(Selection):
    run_id: UUID
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    deadline_at: datetime

    @model_validator(mode="after")
    def aware(self):
        if self.deadline_at.tzinfo is None:
            raise ValueError("Use an absolute native SDK preparation deadline")
        return self


class Policy:
    QUALIFIED = True  # SDK preparation only; no model/Metal/consumer readiness.
    isolated_child = True
    get_settings = staticmethod(lambda: get_settings())
    scope_prefix = staticmethod(lambda identity, memory: [])
    scope_environment = staticmethod(lambda: {})

    def __init__(self, profile):
        self.environment = Environment(profile)

    def permitted(self, body):
        if set(body.permissions) != PERMISSIONS or body.profile != self.environment.PROFILE:
            raise HTTPException(403, "Native SDK preparation requires its fixed profile and permissions")

    def journal(self, identity):
        return runtime_install.load_json(runtime_install.directory(identity) / "native_llama.json")

    def save(self, identity, record):
        runtime_install.atomic_json(runtime_install.directory(identity), "native_llama.json", record)

    def catalog(self):
        root = get_settings().host_data_dir().resolve()
        frozen = self.environment.recipe()
        hardware = collect(root)
        try:
            version = (tuple(map(int, platform.mac_ver()[0].split("."))) + (0, 0, 0))[:3]
            supported = (
                platform.system() == "Darwin"
                and platform.machine() == self.environment.architecture
                and version >= tuple(frozen["minimum_os"])
            )
        except ValueError:
            supported = False
        total = sum(v["size_bytes"] for v in frozen["inputs"])
        free = disk_usage(root).free
        available_ram = (hardware.get("memory") or {}).get("available_mib")
        required = total + sum(v["size_bytes"] for v in frozen["files"].values()) + 64 * 1024**2
        enough = type(available_ram) in {int, float} and available_ram >= 512 and free >= required
        reference = None
        active = root / "runtime" / NAMESPACE / "active.json"
        try:
            if active.exists() or active.is_symlink():
                observed = read_json(active)
                if observed.get("profile") == self.environment.PROFILE:
                    self.environment.resolve_id(root, fingerprint(observed))
                    reference = {
                        "profile": observed["profile"],
                        "manifest_sha256": observed["manifest_sha256"],
                        "environment_id": fingerprint(observed),
                    }
        except (OSError, ValueError):
            reference = None
        return {
            "recipe": frozen,
            "manifest_sha256": fingerprint(frozen),
            "platform_supported": supported,
            "installation_available": bool(supported and enough),
            "installation_notice": ""
            if supported and enough
            else "Native SDK setup requires its matching Mac, 512 MiB estimated available RAM and free application storage",
            "storage": {
                "free_bytes": free,
                "download_bytes": total,
                "required_bytes": required,
            },
            "memory_policy": "Estimated available RAM; no hard/no-swap guarantee",
            "environment": reference,
            "sdk_prepared": reference is not None,
            "inference_tested_now": False,
        }

    def controller(self):
        return Controller(self, self.environment, "native_llama", NAMESPACE, self.environment.remember)


class Controller(OwnedEnvironmentPreparation):
    def inspection(self, manager, identity, **kwargs):
        result = super().inspection(manager, identity, **kwargs)
        record = self.policy.journal(identity)
        process = result.get("process")
        if (
            process
            and not result["alive"]
            and not record.get("cancellation_requested")
            and (
                result["status"] == "succeeded"
                or result["status"] == "interrupted"
                and process.get("exit_code") is None
            )
        ):
            try:
                self.environment.resolve(
                    self.policy.get_settings().host_data_dir(), self.environment.observation(identity)
                )
            except (OSError, ValueError):
                result.update(status="interrupted", environment_prepared=False, requires_inspection=True)
            else:
                result.update(status="succeeded", environment_prepared=True, requires_inspection=False)
        return result


def controller(profile):
    return Policy(profile).controller()


@router.get("")
def catalog(profile: Profile):
    return Policy(profile).catalog()


@router.post("/prepare")
def prepare(body: Preparation):
    return controller(body.profile).start(runtime_install.process_manager(), body)


def observed_profile(identity):
    record = runtime_install.load_json(runtime_install.directory(identity) / "native_llama.json")
    if not record:
        raise HTTPException(404, "Native SDK preparation was not found")
    if record.get("profile") not in PROFILES:
        raise HTTPException(409, "The native SDK preparation profile changed")
    return record["profile"]


@router.get("/{identity}")
def inspect(
    identity: UUID,
    stdout_offset: int = Query(0, ge=0, le=2**63 - 1),
    stderr_offset: int = Query(0, ge=0, le=2**63 - 1),
):
    return controller(observed_profile(identity)).inspection(
        runtime_install.process_manager(), identity, stdout_offset=stdout_offset, stderr_offset=stderr_offset
    )


@router.post("/{identity}/cancel")
def cancel(identity: UUID, body: Selection):
    return controller(body.profile).cancel(runtime_install.process_manager(), identity, body)


@router.post("/{identity}/adopt")
def adopt(identity: UUID, body: Selection):
    if not Policy(body.profile).catalog()["platform_supported"]:
        raise HTTPException(409, "Native SDK activation requires its matching Mac platform")
    selected = controller(body.profile).adopt(runtime_install.process_manager(), identity, body)
    return {
        **selected,
        "environment_id": fingerprint(
            {key: selected[key] for key in ("profile", "operation_id", "manifest_sha256")}
        ),
        "sdk_prepared": True,
        "inference_tested_now": False,
    }
