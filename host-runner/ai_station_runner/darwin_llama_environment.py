"""Verified native SDK environment and opaque identity; never model readiness."""

import re
from pathlib import Path
from uuid import UUID

from ai_station_runner import darwin_llama_bundle as bundle
from ai_station_runner.environment_files import read_json
from ai_station_runner.runtime_install import atomic_json
from ai_station_runner.speech_environment import directory, fingerprint

PROFILES = {
    "llamacpp-native-darwin-arm64-b12032-v2": "arm64",
    "llamacpp-native-darwin-x86_64-b12032-v2": "x86_64",
}
NAMESPACE = "native-llama-environments"


class Environment:
    fingerprint = staticmethod(fingerprint)
    directory = staticmethod(directory)

    def __init__(self, profile):
        if profile not in PROFILES:
            raise ValueError("Select a built-in native llama.cpp profile")
        self.PROFILE = profile
        self.architecture = PROFILES[profile]

    def recipe(self):
        return bundle.recipe(self.architecture)

    def folder(self, root, operation):
        runtime = directory(Path(root).resolve(strict=True), "runtime")
        parent = directory(runtime, NAMESPACE + "/" + fingerprint(self.recipe()))
        return directory(parent, str(UUID(str(operation))))

    def prepare(self, root, operation, *, check=lambda: None, progress=lambda value: None):
        operation = str(UUID(str(operation)))
        bundle.prepare(root, operation, self.architecture, check=check, progress=progress)
        check()
        value = self.observation(operation)
        folder = self.folder(root, operation)
        record = {
            **value,
            "schema": 1,
            "environment_prepared": True,
            "relative_path": folder.relative_to(Path(root).resolve()).as_posix(),
        }
        if (folder / "ready.json").exists() or (folder / "ready.json").is_symlink():
            raise ValueError("Inspect existing native SDK readiness before replacing it")
        atomic_json(folder, "ready.json", record)
        check()
        self.resolve(root, value)
        return record

    def observation(self, operation):
        return {
            "profile": self.PROFILE,
            "operation_id": str(UUID(str(operation))),
            "manifest_sha256": fingerprint(self.recipe()),
        }

    def resolve(self, root, observed):
        if not isinstance(observed, dict) or observed != self.observation(observed.get("operation_id")):
            raise ValueError("The native SDK environment identity changed")
        root = Path(root).resolve(strict=True)
        folder = root / "runtime" / NAMESPACE / observed["manifest_sha256"] / observed["operation_id"]
        if folder.resolve(strict=True) != folder:
            raise ValueError("Native SDK environment storage cannot cross links")
        expected = {
            **observed,
            "schema": 1,
            "environment_prepared": True,
            "relative_path": folder.relative_to(root).as_posix(),
        }
        if read_json(folder / "ready.json") != expected:
            raise ValueError("The native SDK readiness receipt changed")
        checked = bundle.inspect(root, observed["operation_id"], self.architecture)
        return {"observation": observed, "bundle": checked, "architecture": self.architecture}

    def remember(self, root, observed):
        self.resolve(root, observed)
        folder = directory(Path(root).resolve() / "runtime", NAMESPACE + "/identities")
        name = fingerprint(observed) + ".json"
        if (folder / name).exists() or (folder / name).is_symlink():
            if read_json(folder / name) != observed:
                raise ValueError("The native SDK identity mapping changed")
        else:
            atomic_json(folder, name, observed)

    def resolve_id(self, root, identity):
        if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{64}", identity):
            raise ValueError("Use the exact opaque native SDK environment identity")
        observed = read_json(
            Path(root).resolve() / "runtime" / NAMESPACE / "identities" / (identity + ".json")
        )
        if fingerprint(observed) != identity:
            raise ValueError("The native SDK environment mapping changed")
        return self.resolve(root, observed)
