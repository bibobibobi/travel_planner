#!/bin/bash
set -euo pipefail
if (( EUID != 0 || $# != 2 )); then echo 'Invalid invocation' >&2; exit 2; fi
work=$(realpath "$1")
repo=$(realpath "$2")
invoker=${SUDO_USER:?Run through sudo from the test user}
invoker_home=$(getent passwd "$invoker" | cut -d: -f6)
safe_base=$(realpath "$invoker_home/travel-deploy-test")
[[ "${work%/*}" == "$safe_base" && "${work##*/}" == deployment-test-* && -d "$work" ]] || exit 2
id="${work##*-}"
id="${id,,}"
[[ "$id" =~ ^[a-z0-9]{8}$ ]] || exit 2
app="tda${id}"
outsider="tdo${id}"
unit="tdtest${id}.service"
slow_unit="tdtest${id}-slow.service"
for account in "$app" "$outsider"; do
    if getent passwd "$account" >/dev/null || getent group "$account" >/dev/null; then
        echo 'Test account or group already exists' >&2; exit 1
    fi
done
for candidate in "$unit" "$slow_unit"; do
    existing=$(systemctl list-units --all --no-legend --plain --no-pager "$candidate")
    [[ -z "${existing//[[:space:]]/}" ]] || { echo 'Test unit already exists' >&2; exit 1; }
    [[ ! -d "/sys/fs/cgroup/system.slice/$candidate" ]] || { echo 'Test cgroup exists' >&2; exit 1; }
done
jobs=$(systemctl list-jobs --no-legend --plain --no-pager)
while read -r _ candidate _; do
    [[ "$candidate" != "$unit" && "$candidate" != "$slow_unit" ]] || { echo 'Test unit has a pending job' >&2; exit 1; }
done <<< "$jobs"
mountpoint=$(mktemp -d /run/travel-deploy-test.XXXXXXXX)
made_app=0; made_outsider=0; mounted=0
cleanup() {
    local unsafe=0 listing jobs candidate load active sub rest target
    for target in "$unit" "$slow_unit"; do
        if ! listing=$(systemctl list-units --all --no-legend --plain --no-pager "$target"); then unsafe=1; listing=''; fi
        if [[ -n "${listing//[[:space:]]/}" ]] || [[ -d "/sys/fs/cgroup/system.slice/$target" ]]; then
            systemctl stop "$target" || unsafe=1
        fi
        if ! jobs=$(systemctl list-jobs --no-legend --plain --no-pager); then unsafe=1; jobs=''; fi
        while read -r _ candidate rest; do
            if [[ "$candidate" == "$target" ]]; then systemctl stop "$target" || unsafe=1; fi
        done <<< "$jobs"
        if ! jobs=$(systemctl list-jobs --no-legend --plain --no-pager); then unsafe=1; jobs=''; fi
        while read -r _ candidate rest; do [[ "$candidate" != "$target" ]] || unsafe=1; done <<< "$jobs"
        if ! listing=$(systemctl list-units --all --no-legend --plain --no-pager "$target"); then unsafe=1; listing=''; fi
        while read -r candidate load active sub rest; do
            [[ "$candidate" != "$target" ]] && continue
            [[ "$active" == inactive || "$active" == failed ]] || unsafe=1
        done <<< "$listing"
        if [[ -d "/sys/fs/cgroup/system.slice/$target" ]] &&
           { [[ ! -r "/sys/fs/cgroup/system.slice/$target/cgroup.events" ]] ||
             ! grep -qx 'populated 0' "/sys/fs/cgroup/system.slice/$target/cgroup.events"; }; then unsafe=1; fi
    done
    if (( made_app )); then
        if pgrep -u "$app" >/dev/null; then unsafe=1; else [[ $? == 1 ]] || unsafe=1; fi
    fi
    if (( unsafe )); then
        echo "WARNING: preserving mount $mountpoint and accounts $app $outsider: test service not proven stopped" >&2
        return 1
    fi
    if (( mounted )) && ! umount "$mountpoint"; then
        echo "WARNING: unmount $mountpoint and remove $app $outsider manually" >&2; return 1
    fi
    rmdir "$mountpoint" || echo "WARNING: remove $mountpoint manually" >&2
    if (( made_outsider )); then userdel "$outsider" || echo "WARNING: remove $outsider manually" >&2; fi
    if (( made_app )); then userdel "$app" || echo "WARNING: remove $app manually" >&2; fi
    if (( made_outsider )) && getent group "$outsider" >/dev/null; then groupdel "$outsider" || true; fi
    if (( made_app )) && getent group "$app" >/dev/null; then groupdel "$app" || true; fi
}
trap cleanup EXIT
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$app"; made_app=1
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$outsider"; made_outsider=1
chown root:root "$work"
chmod 0755 "$work"
mount --bind "$work" "$mountpoint"; mounted=1
mkdir -m 0755 "$mountpoint/tools"
install -m 0644 "$repo/deploy/server/deployment_controller.py" "$repo/deploy/server/deployment_transaction.py" \
    "$repo/deploy/server/deployment_health.py" "$repo/deploy/server/receive_artifact.py" \
    "$repo/deploy/server/release_tree.py" "$repo/deploy/server/artifact_stream.py" \
    "$repo/deploy/server/integration_deployment.py" "$repo/deploy/server/integration_http_service.py" "$mountpoint/tools/"
/usr/bin/python3 -B "$mountpoint/tools/integration_deployment.py" "$mountpoint" "$app" "$outsider" "$unit"
