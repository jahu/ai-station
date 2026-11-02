#!/usr/bin/env bash
# Explicit developer experiment on one disposable public GitHub Intel host.
# Never called by the consumer launcher, API, Runner or ordinary native checks.
set -euo pipefail
umask 077

[[ "${AI_STATION_REAL_MAC_DOCKER_TESTS:-}" == 1 ]]
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_REPOSITORY:-}" == jahu/ai-station ]]
[[ "${GITHUB_ACTOR:-}" == jahu && "${RUNNER_OS:-}" == macOS && "${RUNNER_ARCH:-}" == X64 ]]
[[ "$(/usr/bin/uname -m)" == x86_64 && "$(/usr/bin/id -u)" != 0 ]]
[[ ! -e /Applications/Docker.app && ! -L /Applications/Docker.app ]]
[[ ! -e "$HOME/Applications/Docker.app" && ! -L "$HOME/Applications/Docker.app" ]]
[[ ! -e "$HOME/.docker" && ! -L "$HOME/.docker" ]]

qa_python="$(command -v python)"
qa_user="$(/usr/bin/id -un)"
qa_root="$PWD/.native-mac"
mkdir -m 700 "$qa_root"
qa_cli=/Applications/Docker.app/Contents/Resources/bin/docker

desktop_cli() {
    /usr/bin/env -i HOME="$HOME" USER="$qa_user" LOGNAME="$qa_user" \
        PATH=/usr/bin:/bin:/usr/sbin:/sbin LANG=C "$qa_cli" "$@"
}

cleanup() {
    qa_status=$?
    trap - EXIT
    set +e
    if [[ "$qa_status" != 0 ]]; then
        # Only this newly installed, account-free developer Desktop's logs.
        for qa_log in "$HOME/Library/Containers/com.docker.docker/Data/log/host/com.docker.backend.log" \
            "$HOME/Library/Containers/com.docker.docker/Data/log/host/Docker Desktop.log"; do
            if [[ -f "$qa_log" ]]; then /usr/bin/tail -n 30 "$qa_log"; fi
        done
    fi
    if [[ -f "$qa_root/desktop-installed" ]]; then
        desktop_cli desktop stop --timeout 60
        if [[ "$?" != 0 && "$qa_status" == 0 ]]; then qa_status=1; fi
    fi
    if [[ -f "$qa_root/mounted" ]]; then
        /usr/bin/hdiutil detach "$qa_root/mount"
        if [[ "$?" != 0 && "$qa_status" == 0 ]]; then qa_status=1; fi
    fi
    exit "$qa_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

/usr/bin/xcrun clang -Wall -Wextra -Werror -framework Hypervisor \
    packaging/macos/hypervisor-probe.c -o "$qa_root/hypervisor"
/usr/bin/codesign --force --sign - --entitlements packaging/macos/hypervisor-probe.entitlements \
    "$qa_root/hypervisor"
/usr/bin/codesign --verify --strict "$qa_root/hypervisor"
"$qa_root/hypervisor" > "$qa_root/hypervisor.json"
"$qa_python" -I -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["empty_vm_created"] and d["empty_vm_destroyed"]' \
    "$qa_root/hypervisor.json"

# Exact publisher 4.97.0 Intel DMG and its published checksum, never "latest".
/usr/bin/curl --fail --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 300 \
    https://desktop.docker.com/mac/main/amd64/244584/Docker.dmg -o "$qa_root/Docker.dmg"
printf '%s  %s\n' 98da1a82dac734ba6a14c3e0379f5655ce0bd52a04cf8bb47f4e4642c914f695 \
    "$qa_root/Docker.dmg" | /usr/bin/shasum -a 256 -c -
mkdir -m 700 "$qa_root/mount"
/usr/bin/hdiutil attach -readonly -nobrowse -mountpoint "$qa_root/mount" "$qa_root/Docker.dmg"
touch "$qa_root/mounted"
/usr/bin/codesign --verify --deep --strict "$qa_root/mount/Docker.app"

# Docker's documented prerequisite install requires administrator setup. This
# acts only inside the throwaway developer VM; it does not install on the user's
# workstation. License acceptance here is confined to this explicit QA operation.
/usr/bin/sudo -n /usr/bin/env -i HOME="$HOME" USER="$qa_user" LOGNAME="$qa_user" \
    PATH=/usr/bin:/bin:/usr/sbin:/sbin LANG=C \
    "$qa_root/mount/Docker.app/Contents/MacOS/install" --accept-license --user="$qa_user"
touch "$qa_root/desktop-installed"
/usr/bin/hdiutil detach "$qa_root/mount"
rm "$qa_root/mounted"
# A fresh headless installation has no Launch Services registration yet. Open
# this exact installed app first; the vendor CLI locates it by bundle identity.
/usr/bin/open -a /Applications/Docker.app
desktop_cli desktop start --timeout 240
# The vendor CLI returns success immediately when the GUI is already running;
# this does not imply its desktop-linux context or daemon is ready yet.
/usr/bin/env -i HOME="$HOME" USER="$qa_user" LOGNAME="$qa_user" \
    PATH=/usr/bin:/bin:/usr/sbin:/sbin LANG=C \
    "$qa_python" -IB scripts/macos_desktop_qa_ready.py | /usr/bin/tee "$qa_root/engine-ready.json"
mkdir -m 700 "$qa_root/Chosen data, Żółw"
/usr/bin/env -i HOME="$HOME" USER="$qa_user" LOGNAME="$qa_user" \
    PATH=/usr/bin:/bin:/usr/sbin:/sbin LANG=C \
    "$qa_python" -IB scripts/macos_transport_probe.py --prepare-image \
    --data-directory "$qa_root/Chosen data, Żółw" --output "$qa_root/bridge-proof"
