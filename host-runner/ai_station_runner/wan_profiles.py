"""Fixed Wan execution profiles; callers never supply loader or scope options."""

DEFAULT = "default"
BOUNDED = "bounded_11g"
MEMORY_MIB = 11264


def validate_profile(request):
    profile = request.get("memory_profile", DEFAULT)
    if not isinstance(profile, str) or profile not in {DEFAULT, BOUNDED}:
        raise ValueError("Unsupported fixed Wan memory profile")
    if profile == BOUNDED and (
        request.get("width") != 1280
        or request.get("height") != 704
        or type(request.get("steps")) is not int
        or not 20 <= request["steps"] <= 40
    ):
        raise ValueError("The bounded Wan profile requires 1280x704 and at least 20 steps")
    return profile


def prepare_job(request):
    """Kernel verification happens before importing ComfyUI, Torch or a model."""
    profile = validate_profile(request)
    if profile == BOUNDED:
        from ai_station_runner.memory_scope import require_scope

        require_scope(request["run_id"], MEMORY_MIB)
        return "fp8_e4m3fn"
    # Only private, bounded engineering probes exercise this field. It is not
    # accepted by either native or control-plane HTTP request schemas.
    precision = request.get("weight_dtype", "default")
    if not isinstance(precision, str) or precision not in {"default", "fp8_e4m3fn"}:
        raise ValueError("Unsupported fixed Wan weight precision")
    return precision
