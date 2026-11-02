"""Native installer ownership handoff; never proof of Docker service quiescence."""

import fcntl
import os
import stat
import time
from contextlib import contextmanager

from desktop_control import request
from desktop_versions import attest, directory, load, namespace, package_identity


def lock_file(root, name, *, create=False):
    directory(root)
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(root / name, flags | (os.O_CREAT if create else 0), 0o600)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
        ):
            raise ValueError("Desktop handoff requires private owned lock files")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def observe(root, config, channel):
    status = request(channel)
    identity = request(channel, "identity")
    package = attest(root, config, status, identity)
    return status["instance_id"], package, load(root)


def require_lock(root, name, descriptor):
    opened, current = os.fstat(descriptor), (root / name).lstat()
    if (
        (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        or opened.st_nlink != 1
        or opened.st_mode & 0o077
        or opened.st_uid != os.geteuid()
    ):
        raise ValueError("Desktop handoff lock identity changed; inspect the installation")


@contextmanager
def handoff(root, config, channel, candidate, consent, *, timeout=90):
    """Consent, re-attest, Stop that instance and hold desktop.lock for the updater.

    The trusted caller verifies candidate package bytes first. This function does
    not migrate data, launch a candidate, kill PIDs or assume containers stopped.
    A later coordinator must inspect owned services before image dispatch.
    """
    candidate = package_identity(candidate)
    if type(timeout) not in (int, float) or not 0 < timeout <= 300:
        raise ValueError("Desktop handoff timeout must be positive and bounded")
    gate = lock_file(root, "desktop-update.lock", create=True)
    owner_lock = None
    try:
        try:
            fcntl.flock(gate, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another desktop update is already being inspected") from None
        owner_lock = lock_file(root, "desktop.lock")
        try:
            fcntl.flock(owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass  # A live native owner is mandatory for this handoff path.
        else:
            raise RuntimeError("The desktop owner already stopped; inspect its pending update")
        instance, previous, receipt = observe(root, config, channel)
        if candidate == previous:
            raise ValueError("This verified desktop version is already installed")
        if candidate["source_epoch"] < previous["source_epoch"]:
            raise ValueError("An older desktop package requires explicit recovery inspection")
        before = namespace(config)
        # The callback is local native UI. It receives copies of safe projected
        # metadata only, never prompts, URLs, commands or filesystem coordinates.
        if consent(previous.copy(), candidate.copy()) is not True:
            yield None
            return
        require_lock(root, "desktop-update.lock", gate)
        require_lock(root, "desktop.lock", owner_lock)
        if observe(root, config, channel) != (instance, previous, receipt) or namespace(config) != before:
            raise ValueError("The desktop owner or storage changed during update consent")
        request(channel, "stop", instance_id=instance)
        deadline = time.monotonic() + timeout
        while True:
            require_lock(root, "desktop-update.lock", gate)
            require_lock(root, "desktop.lock", owner_lock)
            try:
                fcntl.flock(owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if load(root) != receipt or namespace(config) != before:
                    raise ValueError("The desktop owner changed while waiting for Stop")
                if time.monotonic() >= deadline:
                    raise RuntimeError("The desktop is still stopping; inspect it before updating") from None
                time.sleep(0.05)
        require_lock(root, "desktop-update.lock", gate)
        require_lock(root, "desktop.lock", owner_lock)
        if load(root) != receipt or namespace(config) != before:
            raise ValueError("The stopped desktop version or storage no longer matches")
        # Holding the lock prevents normal desktop startup until the caller exits.
        # This is deliberately not a claim about Docker/container-side locks.
        yield {"instance_id": instance, "previous": previous, "candidate": candidate, "data": before[0]}
    finally:
        if owner_lock is not None:
            os.close(owner_lock)
        os.close(gate)
