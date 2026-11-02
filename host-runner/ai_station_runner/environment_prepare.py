"""Owned lifecycle shared by fixed offline environments, never a shell API.

Only built-in native modules construct this policy. HTTP callers cannot choose
its Python module, state location, process executor or storage namespace.
"""

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException

from ai_station_runner import runtime_install
from ai_station_runner.processes import ProcessNotOwned
from ai_station_runner.security import resolve_child


@dataclass(frozen=True)
class OwnedEnvironmentPreparation:
    policy: object
    environment: object
    name: str
    storage_namespace: str
    before_adoption: object = None

    def inspection(self, manager, identity, *, stdout_offset=0, stderr_offset=0):
        identity = str(UUID(str(identity)))
        record = self.policy.journal(identity)
        if record is None:
            raise HTTPException(404, f"{self.name.capitalize()} preparation was not found")
        if record.get("profile") != self.environment.PROFILE:
            raise HTTPException(409, "This native preparation belongs to a different profile")
        result = {
            "run_id": identity,
            "profile": record["profile"],
            "manifest_sha256": record.get("manifest_sha256"),
            "environment_prepared": False,
            "status": "interrupted",
            "alive": False,
            "requires_inspection": True,
            "process": None,
        }
        try:
            process = manager.inspect(identity, stdout_offset=stdout_offset, stderr_offset=stderr_offset)
        except ProcessNotOwned:
            if record.get("cancellation_requested"):
                result.update(status="canceled", requires_inspection=False)
            return result
        if process.get("executor") != self.name + "_environment_setup":
            raise HTTPException(409, "This process belongs to another executor")
        result.update(process=process, alive=process["alive"])
        if process["alive"] or process.get("completion_pending"):
            result.update(
                status="cancel_requested" if record.get("cancellation_requested") else "running",
                requires_inspection=False,
            )
        elif record.get("cancellation_requested"):
            result.update(status="canceled", requires_inspection=False)
        elif process.get("status") == "exited" and process.get("exit_code") == 0:
            root = self.policy.get_settings().host_data_dir().resolve()
            relative = f"runtime/{self.storage_namespace}/{record['manifest_sha256']}/{identity}/ready.json"
            path = resolve_child(root, relative)
            if path != root / relative:
                raise HTTPException(409, f"{self.name.capitalize()} readiness cannot cross a symlink")
            receipt = runtime_install.load_json(path)
            if receipt and all(
                receipt.get(key) == value
                for key, value in {
                    "profile": record["profile"],
                    "operation_id": identity,
                    "manifest_sha256": record["manifest_sha256"],
                    "environment_prepared": True,
                    "relative_path": str(Path(relative).parent),
                }.items()
            ):
                result.update(status="succeeded", environment_prepared=True, requires_inspection=False)
        elif process.get("status") in {"exited", "canceled"}:
            result.update(status="failed", requires_inspection=False)
        return result

    def start(self, manager, body):
        self.policy.permitted(body)
        identity = str(body.run_id)
        value = body.model_dump(mode="json")
        value["permissions"] = sorted(value["permissions"])
        request_hash = self.environment.fingerprint(value)
        with runtime_install.locked():
            if old := self.policy.journal(identity):
                if (
                    old.get("manifest_sha256") not in {None, body.manifest_sha256}
                    or old.get("profile") != body.profile
                ):
                    raise HTTPException(409, f"This operation belongs to a different {self.name} preparation")
                if (
                    not (old.get("cancellation_requested") and old.get("manifest_sha256") is None)
                    and old.get("request_hash") != request_hash
                ):
                    raise HTTPException(409, f"Native {self.name} preparation identity is immutable")
                return self.inspection(manager, identity)
            observed = self.policy.catalog()
            if not observed["installation_available"]:
                raise HTTPException(409, observed["installation_notice"])
            if body.manifest_sha256 != observed["manifest_sha256"]:
                raise HTTPException(409, f"The {self.name} recipe changed; review the current manifest")
            if not 0 < body.deadline_at.timestamp() - time.time() <= 4 * 3600:
                raise HTTPException(
                    422, f"{self.name.capitalize()} preparation needs a future deadline within four hours"
                )
            root = self.policy.get_settings().host_data_dir().resolve()
            record = {
                "profile": body.profile,
                "run_id": identity,
                "manifest_sha256": body.manifest_sha256,
                "deadline_at": body.deadline_at.isoformat(),
                "request_hash": request_hash,
                "cancellation_requested": False,
            }
            self.policy.save(identity, record)
            folder = runtime_install.directory(identity)
            runtime_install.atomic_json(
                folder, self.name + "-request.json", {**record, "data_root": str(root)}
            )
            manager.start(
                run_id=identity,
                argv=[
                    *self.policy.scope_prefix(identity, 4096),
                    sys.executable,
                    *(["-IB"] if getattr(self.policy, "isolated_child", False) else []),
                    "-m",
                    "ai_station_runner." + self.name + "_environment_job",
                    str(folder / (self.name + "-request.json")),
                ],
                cwd=root,
                executor=self.name + "_environment_setup",
                env={
                    "PATH": "/usr/bin:/bin",
                    "LANG": "C.UTF-8",
                    "PYTHONUNBUFFERED": "1",
                    "PYTHONNOUSERSITE": "1",
                    **(
                        {}
                        if getattr(self.policy, "isolated_child", False)
                        else {"PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
                    ),
                    **self.policy.scope_environment(),
                },
                deadline_at=body.deadline_at.timestamp(),
            )
            return self.inspection(manager, identity)

    def cancel(self, manager, identity, body):
        self.policy.permitted(body)
        identity = str(UUID(str(identity)))
        with runtime_install.locked():
            record = self.policy.journal(identity) or {
                "profile": body.profile,
                "run_id": identity,
                "manifest_sha256": None,
            }
            if record.get("profile") != body.profile:
                raise HTTPException(409, "This native preparation belongs to a different profile")
            record["cancellation_requested"] = True
            self.policy.save(identity, record)  # A durable pre-dispatch Stop also prevents a lost-ACK start.
            try:
                process = manager.inspect(identity)
                if process.get("executor") != self.name + "_environment_setup":
                    raise HTTPException(409, "This process belongs to another executor")
                manager.cancel(identity)
            except ProcessNotOwned:
                pass
            return self.inspection(manager, identity)

    def adopt(self, manager, identity, body):
        self.policy.permitted(body)
        if not self.policy.QUALIFIED:
            raise HTTPException(409, f"Managed {self.name} activation is still being qualified")
        identity = str(UUID(str(identity)))
        with runtime_install.locked():
            result = self.inspection(manager, identity)
            if result["status"] != "succeeded" or not result["environment_prepared"] or result["alive"]:
                raise HTTPException(
                    409, f"Inspect the completed native {self.name} preparation before activation"
                )
            current = self.environment.fingerprint(self.environment.recipe())
            if current != result["manifest_sha256"]:
                raise HTTPException(409, f"The native {self.name} recipe changed before activation")
            root = self.policy.get_settings().host_data_dir().resolve()
            folder = self.environment.directory(root / "runtime", self.storage_namespace)
            selected = {"profile": body.profile, "operation_id": identity, "manifest_sha256": current}
            if self.before_adoption is not None:
                self.before_adoption(root, selected)
            runtime_install.atomic_json(folder, "active.json", selected)
            return {**selected, "environment_prepared": True, self.name + "_inference_tested_now": False}
