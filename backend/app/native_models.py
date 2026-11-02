"""Native llama.cpp coordinates within existing model preparation/load Runs."""

import re

PROFILES = (
    "llamacpp-native-darwin-arm64-b12032-v2",
    "llamacpp-native-darwin-x86_64-b12032-v2",
)


def native(values):
    return values.get("runtime_profile") in PROFILES


def verification(values):
    result = {"runtime_profile": values["runtime_profile"], "check_context": True}
    if native(values):
        result.update(
            environment_id=values.get("environment_id"),
            context_size=values["context_size"],
            check_image=False,
        )
    return result


def ready(report, values):
    if native(values):
        observed = report.get("native") or {}
        return bool(
            observed.get("present")
            and observed.get("runtime_profile") == values["runtime_profile"]
            and observed.get("environment_id") == values["environment_id"]
        )
    return bool((report.get("image") or {}).get("present"))


def host_profile(hardware):
    host = hardware.get("host") or {}
    if host.get("system") == "Darwin" and host.get("architecture") in {"arm64", "x86_64"}:
        return "llamacpp-native-darwin-" + host["architecture"] + "-b12032-v2"
    return None


def active_environment(profile):
    from app.native_llama_setup_client import NativeLlamaSetupClient
    from app.runner_client import RunnerError, RunnerUnavailable

    try:
        report = NativeLlamaSetupClient(timeout=30).runtime_setup_catalog(profile=profile)
    except (RunnerError, RunnerUnavailable):
        return None
    value = report.get("environment")
    if (
        report.get("platform_supported")
        and report.get("sdk_prepared")
        and isinstance(value, dict)
        and value.get("profile") == profile
    ):
        identity = value.get("environment_id")
        if isinstance(identity, str) and re.fullmatch(r"[a-f0-9]{64}", identity):
            return identity
    return None
