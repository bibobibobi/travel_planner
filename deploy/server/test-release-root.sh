#!/bin/bash
set -euo pipefail
if (( EUID != 0 || $# != 3 )) || [[ "$3" != '' && "$3" != '--cgroup-only' ]]; then
    echo 'Invalid invocation' >&2; exit 2
fi
work=$(realpath "$1")
repo=$(realpath "$2")
invoker=${SUDO_USER:?Run through sudo from the test user}
invoker_home=$(getent passwd "$invoker" | cut -d: -f6)
safe_base=$(realpath "$invoker_home/travel-deploy-test")
[[ "${work%/*}" == "$safe_base" && "${work##*/}" == release-integration-* && -d "$work" && ! -L "$work" ]] || exit 2
test_id="${work##*-}"
test_id="${test_id,,}"
[[ "$test_id" =~ ^[a-z0-9]{8}$ ]] || exit 2
builder="trb${test_id}"
app="tra${test_id}"
deploy="trd${test_id}"
unit_prefix="trtest${test_id}"
existing_units=$(systemctl list-units --all --no-legend --plain --no-pager "${unit_prefix}-*.service")
if [[ -n "${existing_units//[[:space:]]/}" ]]; then echo 'Test unit prefix is already in use' >&2; exit 1; fi
existing_jobs=$(systemctl list-jobs --no-legend --plain --no-pager)
while read -r _ existing_service _; do
    if [[ "$existing_service" == "${unit_prefix}"-*.service ]]; then
        echo 'Test unit prefix has a pending job' >&2; exit 1
    fi
done <<< "$existing_jobs"
for existing_group in /sys/fs/cgroup/system.slice/"${unit_prefix}"-*.service; do
    if [[ -d "$existing_group" ]]; then echo 'Test cgroup prefix is already in use' >&2; exit 1; fi
done
for account in "$builder" "$app" "$deploy"; do
    if getent passwd "$account" >/dev/null; then echo 'Test account already exists' >&2; exit 1; fi
done
mountpoint=$(mktemp -d /run/travel-release-test.XXXXXXXX)
made_builder=0; made_app=0; made_deploy=0; mounted=0
cleanup() {
    local group service listing jobs load active sub rest result unsafe=0
    # Only names using this run's random prefix are ever stopped.
    if ! listing=$(systemctl list-units --all --no-legend --plain --no-pager "${unit_prefix}-*.service"); then
        unsafe=1
        listing=''
    fi
    while read -r service load active sub rest; do
        [[ "$service" == "${unit_prefix}"-*.service ]] || continue
        systemctl stop "$service" || unsafe=1
    done <<< "$listing"
    if ! jobs=$(systemctl list-jobs --no-legend --plain --no-pager); then unsafe=1; jobs=''; fi
    while read -r _ service rest; do
        [[ "$service" == "${unit_prefix}"-*.service ]] || continue
        systemctl stop "$service" || unsafe=1
    done <<< "$jobs"
    for group in /sys/fs/cgroup/system.slice/"${unit_prefix}"-*.service; do
        [[ -d "$group" ]] || continue
        service=${group##*/}
        systemctl stop "$service" || unsafe=1
        if [[ -d "$group" ]] && { [[ ! -r "$group/cgroup.events" ]] || ! grep -qx 'populated 0' "$group/cgroup.events"; }; then unsafe=1; fi
    done
    if ! listing=$(systemctl list-units --all --no-legend --plain --no-pager "${unit_prefix}-*.service"); then
        unsafe=1
        listing=''
    fi
    while read -r service load active sub rest; do
        [[ "$service" == "${unit_prefix}"-*.service ]] || continue
        [[ "$active" == inactive || "$active" == failed ]] || unsafe=1
    done <<< "$listing"
    if ! jobs=$(systemctl list-jobs --no-legend --plain --no-pager); then unsafe=1; jobs=''; fi
    while read -r _ service rest; do
        if [[ "$service" == "${unit_prefix}"-*.service ]]; then unsafe=1; fi
    done <<< "$jobs"
    if (( made_builder )); then
        if pgrep -u "$builder" >/dev/null; then
            unsafe=1
        else
            result=$?
            if (( result != 1 )); then unsafe=1; fi
        fi
    fi
    if (( unsafe )); then
        echo "WARNING: unable to prove test units stopped; preserving mount $mountpoint and accounts $builder $app $deploy" >&2
        return 1
    fi
    if (( mounted )) && ! umount "$mountpoint"; then
        echo "WARNING: unmount $mountpoint and remove $builder $app $deploy manually" >&2
        return 1
    fi
    rmdir "$mountpoint" 2>/dev/null || echo "WARNING: remove empty directory $mountpoint manually" >&2
    cleanup_account "$deploy" "$made_deploy"
    cleanup_account "$app" "$made_app"
    cleanup_account "$builder" "$made_builder"
}
cleanup_account() {
    local account=$1 created=$2
    (( created )) || return 0
    userdel "$account" || { echo "WARNING: remove $account manually" >&2; return 0; }
    if getent group "$account" >/dev/null; then
        groupdel "$account" || echo "WARNING: remove group $account manually" >&2
    fi
}
trap cleanup EXIT
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$builder"; made_builder=1
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$app"; made_app=1
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$deploy"; made_deploy=1
chown root:root "$work"
chmod 0755 "$work"
mount --bind "$work" "$mountpoint"; mounted=1
mkdir -m 0755 "$mountpoint/tools"
install -m 0644 "$repo/deploy/server/release_builder.py" "$repo/deploy/server/release_tree.py" \
    "$repo/deploy/server/receive_artifact.py" "$repo/deploy/server/artifact_stream.py" \
    "$repo/deploy/server/release_build_worker.py" "$repo/deploy/server/integration_release.py" \
    "$repo/deploy/server/integration_cgroup.py" "$mountpoint/tools/"
install -m 0755 "$repo/scripts/extract_artifact.py" "$repo/scripts/validate_artifact.py" "$mountpoint/tools/"
if [[ "$3" == '--cgroup-only' ]]; then
    /usr/bin/python3 -B "$mountpoint/tools/integration_cgroup.py" "$mountpoint" "$builder" "$unit_prefix"
else
    /usr/bin/python3 -B "$mountpoint/tools/integration_release.py" "$mountpoint" "$builder" "$app" "$deploy" "$unit_prefix"
fi
