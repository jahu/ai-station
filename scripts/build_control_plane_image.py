"""Developer packaging build: native frontend, selected target runtime, local image only."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def recipe(source):
    first, separator, rest = source.partition(b"\n")
    if first != b"FROM node:22-alpine AS frontend" or not separator:
        raise ValueError("Review the canonical frontend stage before changing the cross-platform recipe")
    # BuildKit supplies BUILDPLATFORM. Keep the ordinary/legacy Dockerfile intact.
    return b"FROM --platform=$BUILDPLATFORM node:22-alpine AS frontend\n" + rest


def docker(*arguments):
    return subprocess.run(["docker", *arguments], capture_output=True, text=True, timeout=30, check=False)


def build(output, *, platform, builder, tag, buildx=None):
    if platform not in {"linux/amd64", "linux/arm64"}:
        raise ValueError("Choose an explicitly supported control-plane architecture")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", builder):
        raise ValueError("Choose an existing developer builder by name")
    if not re.fullmatch(r"ai-station:[a-z0-9][a-z0-9_.-]{0,100}", tag):
        raise ValueError("Use a project-owned local image tag")
    source = (ROOT / "Dockerfile").read_bytes()
    generated = recipe(source)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        raise ValueError("Commit the source before building a reviewed package image")
    previous = docker("image", "inspect", tag)
    if previous.returncode == 0:
        raise ValueError("The image tag already exists; it was not overwritten")
    if "no such image" not in previous.stderr.lower():
        raise RuntimeError("Image absence could not be confirmed; no build started")
    output = Path(output)
    if output.resolve() != output or output.parent.resolve(strict=True) != output.parent:
        raise ValueError("Choose a canonical new package proof directory")
    output.mkdir(mode=0o700)  # Never adopt or replay uncertain build output.
    frozen = {
        "status": "building",
        "source_head": head,
        "platform": platform,
        "builder": builder,
        "image_tag": tag,
        "canonical_dockerfile_sha256": hashlib.sha256(source).hexdigest(),
        "generated_dockerfile_sha256": hashlib.sha256(generated).hexdigest(),
    }

    def publish():
        path = output / "build.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as target:
            json.dump(frozen, target, indent=2)

    (output / "Dockerfile.generated").write_bytes(generated)
    publish()
    command = [str(buildx)] if buildx is not None else ["docker", "buildx"]
    command += [
        "build",
        "--builder",
        builder,
        "--platform",
        platform,
        "--file",
        "-",
        "--load",
        "--provenance=false",
        "--sbom=false",
        "--progress",
        "plain",
        "--metadata-file",
        str(output / "metadata.json"),
        "--tag",
        tag,
        str(ROOT),
    ]
    try:
        with (output / "build.log").open("x") as log:
            subprocess.run(command, input=generated, stdout=log, stderr=subprocess.STDOUT, check=True)
        observed = docker("image", "inspect", tag)
        if observed.returncode:
            raise RuntimeError("The built local image could not be inspected")
        rows = json.loads(observed.stdout)
        metadata = json.loads((output / "metadata.json").read_text())
        if (
            not isinstance(rows, list)
            or len(rows) != 1
            or not isinstance(rows[0], dict)
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", str(rows[0].get("Id", "")))
            or rows[0].get("Os") != "linux"
            or rows[0].get("Architecture") != platform.split("/")[1]
            or rows[0].get("Config", {}).get("User") != "1000:1000"
            or rows[0].get("Id")
            not in {metadata.get("containerimage.digest"), metadata.get("containerimage.config.digest")}
        ):
            raise ValueError("The built image differs from its source/target receipt")
        frozen.update(
            status="built_image_only",
            image_id=rows[0]["Id"],
            runtime_qualified=False,
            consumer_installer_qualified=False,
        )
    except BaseException as exc:
        frozen.update(status="inspection_required", error_type=type(exc).__name__)
        raise
    finally:
        publish()
    return frozen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=["linux/amd64", "linux/arm64"])
    parser.add_argument("--builder", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--buildx", type=Path, help="Optional already-verified standalone Buildx executable")
    args = parser.parse_args()
    result = build(
        args.output, platform=args.platform, builder=args.builder, tag=args.tag, buildx=args.buildx
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
