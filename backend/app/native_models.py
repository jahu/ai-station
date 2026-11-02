"""Native llama.cpp coordinates within existing model preparation/load Runs."""

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
            environment_id=values["environment_id"],
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
