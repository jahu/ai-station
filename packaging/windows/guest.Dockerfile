# Dedicated WSL guest filesystem; this build never starts a Docker daemon.
FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852
ENV DEBIAN_FRONTEND=noninteractive
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod 755 /usr/sbin/policy-rc.d
COPY station.deb /tmp/station.deb
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates systemd systemd-sysv dbus dbus-user-session \
    docker.io docker-compose-v2 /tmp/station.deb \
    && rm /tmp/station.deb \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* \
    && useradd --create-home --uid 1001 --shell /bin/bash station \
    && chmod 700 /home/station \
    && usermod --append --groups docker station \
    && install -d -m 755 /var/lib/systemd/linger \
    && touch /var/lib/systemd/linger/station \
    && systemctl enable docker.service containerd.service \
    && truncate -s 0 /etc/machine-id \
    && rm -f /var/lib/dbus/machine-id \
    && ln -s /etc/machine-id /var/lib/dbus/machine-id
COPY wsl.conf /etc/wsl.conf
COPY guest_control.py /usr/libexec/ai-station/wsl-control
COPY guest-build.json /usr/lib/ai-station-wsl-build.json
RUN chmod 755 /usr/libexec/ai-station/wsl-control && chmod 644 /etc/wsl.conf /usr/lib/ai-station-wsl-build.json \
    && /usr/lib/ai-station/python/bin/python3 -IBS /usr/lib/ai-station/scripts/windows_gpu_install.py --image-build \
    && rm /usr/sbin/policy-rc.d
# WSL's init starts systemd. This CMD is not a public executor or nested-daemon test.
CMD ["/sbin/init"]
