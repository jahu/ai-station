"""Linux addresses for already-validated owned sockets under long data roots.

The server binds and clients connect through an open parent-directory descriptor.
The socket file stays at its real owned location. Callers retain their existing
path/ownership validation; this helper does not authorize a filesystem path.
"""

import os
import sys
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def unix_address(path: Path):
    if len(os.fsencode(path)) < 108:
        yield str(path)
        return
    if sys.platform != "linux":
        raise ValueError("This platform needs a shorter private Unix socket path")
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        address = f"/proc/self/fd/{descriptor}/{path.name}"
        if len(os.fsencode(address)) >= 108:
            raise ValueError("The private Unix socket filename is too long")
        yield address
    finally:
        os.close(descriptor)
