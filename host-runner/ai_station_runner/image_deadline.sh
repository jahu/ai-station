#!/bin/sh
set -eu
umask 077
deadline="$1"
shift
remaining=$((deadline - $(date +%s)))
[ "$remaining" -gt 0 ] || exit 124
[ -r /sys/fs/cgroup/memory.max ] &&
[ "$(cat /sys/fs/cgroup/memory.max)" = "12884901888" ] &&
[ "$(cat /sys/fs/cgroup/memory.swap.max)" = "0" ] || exit 125
exec /usr/bin/timeout --signal=TERM --kill-after=10s "$remaining" "$@"
