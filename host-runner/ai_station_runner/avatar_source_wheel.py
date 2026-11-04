"""One reviewed pure-Python source exception; no general package-building API."""

import hashlib

from ai_station_runner.speech_environment import unpack_tar

SOURCE_SHA = "f224469b4168294902bb1efa80a8bf7855f24c99aef99cbefc1bcd3cce77881b"
WHEEL_SHA = "e403b2aa433c161c3ed3dc04e9176db63aef53c6dc0af5bb9617748e9c0dd1ba"
BUILD = """
import os, sys, importlib.metadata as metadata
os.umask(0o077)
assert sys.version_info[:3] == (3, 10, 21)
assert metadata.version('setuptools') == '79.0.1'
assert metadata.version('wheel') == '0.45.1'
def offline(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto'}:
        raise PermissionError('Offline fixed source build')
sys.addaudithook(offline)
from setuptools.build_meta import build_wheel
build_wheel(sys.argv[1])
"""


def build_program(python_version=(3, 10, 21)):
    # The source wheel was reproduced on both fixed preparation interpreters.
    # Native profile code chooses one; requests cannot choose a Python version.
    if python_version not in ((3, 10, 21), (3, 12, 14)):
        raise ValueError("Use a qualified fixed source-build Python")
    return BUILD.replace("(3, 10, 21)", repr(python_version))


def build(python, folder, frozen, objects, *, check, run_command, python_version=(3, 10, 21)):
    program = build_program(python_version)
    source = next(v for v in frozen["inputs"] if v["kind"] == "sdist")
    expected = frozen["derived_wheel"]
    if (
        source["name"] != "antlr4-python3-runtime"
        or source["version"] != "4.9.3"
        or source["sha256"] != SOURCE_SHA
        or source["size_bytes"] != 117034
        or expected
        != dict(filename="antlr4_python3_runtime-4.9.3-py3-none-any.whl", sha256=WHEEL_SHA, size_bytes=144590)
    ):
        raise ValueError("Only the reviewed fixed ANTLR source build is allowed")
    tools = [v for v in frozen["inputs"] if v.get("build_tool") is True]
    if {v["name"]: v["version"] for v in tools} != {"setuptools": "79.0.1", "wheel": "0.45.1"}:
        raise ValueError("The source build requires its exact reviewed tools")
    lock = folder / "build-requirements.lock"
    lock.write_text(
        "\n".join(f"{v['name']}=={v['version']} --hash=sha256:{v['sha256']}" for v in tools) + "\n"
    )
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
    destination = folder / "source-build"
    destination.mkdir(mode=0o700)
    extracted = unpack_tar(objects[source["filename"]], destination, check)
    run_command([python, "-I", "-c", program, str(folder / "wheels")], folder=extracted, check=check)
    path = folder / "wheels" / expected["filename"]
    if path.resolve() != path or not path.is_file() or path.stat().st_size != expected["size_bytes"]:
        raise ValueError("The fixed derived wheel changed its path or size")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]:
        raise ValueError("The fixed source wheel was not reproduced exactly")
    return [{**expected, "name": source["name"], "version": source["version"]}]
