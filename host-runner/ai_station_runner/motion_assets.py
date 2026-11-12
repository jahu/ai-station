"""Fixed local fonts and animation code; sources cannot provide asset paths."""

import os
import shutil
from pathlib import Path

FONTS = ("inter", "manrope", "eb-garamond", "jetbrains-mono")


def regular(path):
    path = Path(path).absolute()
    if path.resolve() != path or not path.is_file():
        raise ValueError("Motion dependencies must be regular canonical files")
    return path


def asset_names(request):
    names, visual = {}, 0
    for source in request.sources:
        suffix = Path(source.relative_path).suffix.lower()
        allowed = {"image": {".png", ".jpg", ".jpeg", ".webp"}, "video": {".mp4"}, "audio": {".wav"}}
        if suffix not in allowed[source.kind]:
            raise ValueError("Use a canonical inspected motion source")
        if suffix == ".jpeg":
            suffix = ".jpg"
        name = "assets/mix.wav" if source.kind == "audio" else f"assets/media-{visual}{suffix}"
        visual += source.kind != "audio"
        names[str(source.artifact_id)] = name
    return names


def stage_assets(sdk, destination):
    modules = Path(sdk) / "node_modules"
    assets = destination / "assets"
    (assets / "fonts").mkdir(parents=True)
    shutil.copyfile(regular(modules / "gsap/dist/gsap.min.js"), assets / "gsap.min.js")
    for name in FONTS:
        source = modules / "@fontsource-variable" / name
        target = assets / "fonts" / name
        (target / "files").mkdir(parents=True)
        for item in ("index.css", "LICENSE"):
            shutil.copyfile(regular(source / item), target / item)
        for item in (source / "files").glob("*.woff2"):
            shutil.copyfile(regular(item), target / "files" / item.name)


def request_digest(request):
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def container_limits():
    if os.getuid() == 0 or Path("/dev/dri").exists() or Path("/dev/nvidia0").exists():
        raise ValueError("Motion rendering requires an unprivileged CPU container")
    group = Path("/sys/fs/cgroup")
    if (group / "memory.max").read_text().strip() != str(4096 * 1024**2) or (
        group / "memory.swap.max"
    ).read_text().strip() != "0":
        raise ValueError("Motion container RAM and zero-swap bounds changed")
    if (group / "cpu.max").read_text().split() != ["400000", "100000"] or (
        group / "pids.max"
    ).read_text().strip() != "512":
        raise ValueError("Motion container CPU/process bounds changed")
    if {p.name for p in Path("/sys/class/net").iterdir()} != {"lo"}:
        raise ValueError("Motion container must have a private loopback-only network")
    return {
        "maximum_ram_mib": 4096,
        "maximum_swap_mib": 0,
        "maximum_cpus": 4,
        "maximum_processes": 512,
        "network": "none",
        "gpu": "none",
    }
