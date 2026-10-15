"""Local source compatibility identity; never credentials or attestation."""

from hashlib import sha256
from pathlib import Path


def source_fingerprint(package: Path | None = None) -> str:
    package = package if package is not None else Path(__file__).resolve().parent
    digest = sha256()
    sources = sorted(path for path in package.rglob("*.py") if "__pycache__" not in path.parts)
    if not sources:
        raise RuntimeError("Host Runner source package is missing")
    for path in sources:
        name = path.relative_to(package).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


# Snapshot at import: changing disk files must not relabel an old process.
SOURCE_FINGERPRINT = source_fingerprint()
