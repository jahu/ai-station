"""Four reviewed pure-Python build exceptions for the frozen Live profile."""

import hashlib

from ai_station_runner.avatar_source_wheel import build_program
from ai_station_runner.speech_environment import unpack_tar

EXPECTED = {
    "antlr4-python3-runtime": ("4.9.3", "e403b2aa433c161c3ed3dc04e9176db63aef53c6dc0af5bb9617748e9c0dd1ba"),
    "crcmod": ("1.7", "e2a2a5e699245a298fafdc68d8b4d1edc41bf3775a7b628b0c520eaeced51788"),
    "jieba": ("0.42.1", "49ca5d468e648b5acb7634e0c8cf168857b7eca9a57038b897496091fe616cfc"),
    "oss2": ("2.19.1", "5d0c1226da1dc4fe05e3f8cdc99dbf358b4036f326ebe6d3a89f4fa5d30eb16b"),
}


def build(python, folder, frozen, objects, *, check, run_command):
    sources = {v["name"]: v for v in frozen["inputs"] if v["kind"] == "sdist"}
    derived = {v["name"]: v for v in frozen["derived_wheels"]}
    tools = [v for v in frozen["inputs"] if v.get("build_tool") is True]
    if (
        set(sources) != set(EXPECTED)
        or set(derived) != set(EXPECTED)
        or {v["name"]: v["version"] for v in tools} != {"setuptools": "79.0.1", "wheel": "0.45.1"}
    ):
        raise ValueError("Live source builds require their four fixed packages and tools")
    lock = folder / "build-requirements.lock"
    lock.write_text("\n".join(f"{v['name']}=={v['version']} --hash=sha256:{v['sha256']}" for v in tools))
    run_command(
        [
            python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--require-hashes",
            "--only-binary",
            ":all:",
            "--find-links",
            str(folder / "wheels"),
            "-r",
            str(lock),
        ],
        folder=folder,
        check=check,
    )
    result = []
    for name, (version, digest) in EXPECTED.items():
        source, expected = sources[name], derived[name]
        if (
            source["version"] != version
            or expected["version"] != version
            or expected["sha256"] != digest
            or expected["source_sha256"] != source["sha256"]
        ):
            raise ValueError("The reviewed Live source build changed")
        destination = folder / "sources" / name
        destination.mkdir(mode=0o700)
        extracted = unpack_tar(objects[source["filename"]], destination, check)
        program = build_program((3, 12, 14))
        if name == "crcmod":
            # Its reviewed setup.py falls back to pure Python when no compiler is
            # present. Make that deterministic even on a developer workstation.
            program = "import os\nos.environ.update(CC='/bin/false', CXX='/bin/false')\n" + program
        run_command([python, "-I", "-c", program, str(folder / "wheels")], folder=extracted, check=check)
        path = folder / "wheels" / expected["filename"]
        if (
            path.resolve() != path
            or not path.is_file()
            or path.stat().st_size != expected["size_bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("A Live source wheel was not reproduced exactly")
        result.append({k: expected[k] for k in ("name", "version", "filename", "sha256", "size_bytes")})
    return result
