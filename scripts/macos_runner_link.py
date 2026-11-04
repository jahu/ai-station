"""Native supervisor ownership of one private, ephemeral Runner connection."""

import shutil
from pathlib import Path
from uuid import uuid4

from desktop_link import NativeOwner, directory, prepare_credentials


class NativeConnection:
    def __init__(self, environment):
        self.environment = environment
        self.socket = Path(environment["AI_STATION_RUNNER_SOCKET"])
        self.root = None
        self.identity = None
        self.owner = None
        self.attempted = False

    def start(self):
        if self.attempted:
            raise ValueError("A native connection generation cannot be started twice")
        parent = directory(self.socket.parent)
        data = Path(self.environment["AI_STATION_DATA_HOST_PATH"])
        if not data.is_absolute() or data.resolve(strict=True) != data or parent.is_relative_to(data):
            raise ValueError("Native connection credentials must stay outside canonical mounted app data")
        self.attempted = True
        self.root = parent / ("connection-" + uuid4().hex)
        try:
            self.root.mkdir(mode=0o700)
            info = directory(self.root).stat()
            self.identity = (info.st_dev, info.st_ino)
            material = self.root / "credentials"
            prepare_credentials(material)
            self.owner = NativeOwner(material / "server", self.socket).start()
            self.environment.update(
                AI_STATION_NATIVE_CONNECTION_DIR=str(material / "client"),
                AI_STATION_NATIVE_CONNECTION_PORT=str(self.owner.port),
            )
            return self
        except BaseException:
            # No application container has been dispatched by this operation.
            self.close(remove_credentials=True)
            raise

    def check(self):
        if self.owner is None or self.owner.process.poll() is not None:
            raise RuntimeError("The private native Runner connection exited unexpectedly")

    def close(self, *, remove_credentials):
        if self.owner is not None:
            self.owner.close()
        if not remove_credentials or self.root is None:
            return
        if self.identity is None:
            # Root creation could not attest its identity; preserve an
            # unrecognized path rather than attempting cleanup.
            return
        info = directory(self.root).stat()
        if (info.st_dev, info.st_ino) != self.identity:
            raise ValueError("Connection credential storage changed; replacement was preserved")
        shutil.rmtree(self.root)
        self.root = None
        self.identity = None
