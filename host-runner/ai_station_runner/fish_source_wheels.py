"""Three fixed Fish dependencies without published wheels; no general build API."""

import hashlib
from pathlib import Path

from ai_station_runner import avatar_source_wheel
from ai_station_runner.speech_environment import unpack_tar

SOURCES = {
    "antlr4-python3-runtime": {
        "version": "4.9.3",
        "filename": "antlr4-python3-runtime-4.9.3.tar.gz",
        "size_bytes": 117034,
        "sha256": avatar_source_wheel.SOURCE_SHA,
    },
    "argbind": {
        "version": "0.3.9",
        "filename": "argbind-0.3.9.tar.gz",
        "size_bytes": 17567,
        "sha256": "1b159c04af56858a91d59c7a47bc9ea39d96adfce1d7fcfa38050d7ac9815745",
    },
    "randomname": {
        "version": "0.2.1",
        "filename": "randomname-0.2.1.tar.gz",
        "size_bytes": 64242,
        "sha256": "b79b98302ba4479164b0a4f87995b7bebbd1d91012aeda483341e3e58ace520e",
    },
}
WHEELS = {
    "antlr4-python3-runtime": {
        "filename": "antlr4_python3_runtime-4.9.3-py3-none-any.whl",
        "size_bytes": 144590,
        "sha256": avatar_source_wheel.WHEEL_SHA,
    },
    "argbind": {
        "filename": "argbind-0.3.9-py2.py3-none-any.whl",
        "size_bytes": 11818,
        "sha256": "ef4b811f0c6c49ca3feb64ef39cd5ed05bd8ac4631695bba033f7251b6df26cc",
    },
    "randomname": {
        "filename": "randomname-0.2.1-py3-none-any.whl",
        "size_bytes": 89287,
        "sha256": "9ad5404496211781fd49c8cf03a0cbda6d5cf795a4d7bece496d8b2202d1730e",
    },
}


def validate(frozen):
    sources = [v for v in frozen["inputs"] if v["kind"] == "sdist"]
    if len(sources) != len(SOURCES) or {v["name"] for v in sources} != set(SOURCES):
        raise ValueError("Only the three reviewed Fish source dependencies may be built")
    for item in sources:
        if any(item.get(key) != expected for key, expected in SOURCES[item["name"]].items()):
            raise ValueError("The fixed Fish source dependency changed")
    if frozen.get("derived_wheels") != WHEELS:
        raise ValueError("The reproduced Fish wheels must match the reviewed profile")
    return {v["name"]: v for v in sources}


def wheel_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(python, folder, frozen, objects, *, check, run_command):
    sources = validate(frozen)
    # Reuse the already-qualified fixed Python/tool versions and ANTLR build.
    antlr = {
        **frozen,
        "inputs": [
            v for v in frozen["inputs"] if v["kind"] != "sdist" or v["name"] == "antlr4-python3-runtime"
        ],
        "derived_wheel": WHEELS["antlr4-python3-runtime"],
    }
    result = avatar_source_wheel.build(
        python, folder, antlr, objects, check=check, run_command=run_command, python_version=(3, 12, 14)
    )
    for name in ("argbind", "randomname"):
        check()
        item, expected = sources[name], WHEELS[name]
        archive = Path(objects[item["filename"]])
        if archive.stat().st_size != item["size_bytes"] or wheel_digest(archive) != item["sha256"]:
            raise ValueError("The fixed Fish source object changed")
        destination = folder / ("source-build-" + name)
        destination.mkdir(mode=0o700)
        extracted = unpack_tar(archive, destination, check)
        run_command(
            [python, "-I", "-c", avatar_source_wheel.build_program((3, 12, 14)), str(folder / "wheels")],
            folder=extracted,
            check=check,
        )
        path = folder / "wheels" / expected["filename"]
        if (
            path.resolve() != path
            or not path.is_file()
            or path.stat().st_size != expected["size_bytes"]
            or wheel_digest(path) != expected["sha256"]
        ):
            raise ValueError("The fixed Fish wheel was not reproduced exactly")
        result.append({**expected, "name": name, "version": item["version"]})
    check()
    return result
