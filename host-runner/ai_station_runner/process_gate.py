"""Internal fixed exec barrier. Not a Runner endpoint or a user command tool."""

import os
import select
import sys


def main():
    if len(sys.argv) < 3 or not sys.argv[1].isascii() or not sys.argv[1].isdigit():
        raise SystemExit("Invalid internal launch barrier")
    descriptor = int(sys.argv[1])
    if descriptor < 3:
        raise SystemExit("Invalid internal launch channel")
    os.set_inheritable(descriptor, False)
    try:
        ready, _, _ = select.select([descriptor], [], [], 30)
        if not ready or os.read(descriptor, 2) != b"1":
            raise SystemExit("Native workload was not released by its owner")
    finally:
        os.close(descriptor)
    os.execvpe(sys.argv[2], sys.argv[2:], os.environ)


if __name__ == "__main__":
    main()
