#!/bin/bash
set -Eeuo pipefail
report_failure() {
    local status=$1 line=$2
    printf 'ERROR: Pipeline test failed at line %s (exit %s)\n' "$line" "$status" >&2
}
trap 'report_failure "$?" "$LINENO"' ERR
export PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C
if (( EUID != 0 || $# != 3 )) || [[ "$3" != '' && "$3" != '--recovery-only' ]]; then
    echo 'Invalid invocation' >&2; exit 2
fi
work=$(realpath "$1")
repo=$(realpath "$2")
invoker=${SUDO_USER:?Run through sudo from the test user}
invoker_home=$(getent passwd "$invoker" | cut -d: -f6)
safe_base=$(realpath "$invoker_home/travel-deploy-test")
[[ "${work%/*}" == "$safe_base" && "${work##*/}" == pipeline-test-* && -d "$work" ]] || {
    echo 'ERROR: invalid test directory' >&2; exit 2
}
id="${work##*-}"; id="${id,,}"
[[ "$id" =~ ^[a-z0-9]{8}$ ]] || { echo 'ERROR: invalid test identifier' >&2; exit 2; }
builder="tpb${id}"; app="tpa${id}"; deploy="tpd${id}"
unit="tptest${id}.service"; prefix="tpbuild${id}"
unit_file="/run/systemd/system/$unit"
if [[ -e "$unit_file" || -L "$unit_file" ]]; then echo 'Test unit file already exists' >&2; exit 1; fi
if unit_files=$(systemctl list-unit-files --no-legend --no-pager); then
    :
else
    status=$?
    printf 'ERROR: systemctl list-unit-files failed (exit %s)\n' "$status" >&2
    exit "$status"
fi
while read -r candidate _; do
    if [[ "$candidate" == "$unit" || "$candidate" == "${prefix}"-*.service ]]; then
        echo "ERROR: test unit name is already installed: $candidate" >&2; exit 1
    fi
done <<< "$unit_files"
for unit_dir in /etc/systemd/system /run/systemd/system /usr/lib/systemd/system /lib/systemd/system; do
    if [[ -e "$unit_dir/$unit.d" || -L "$unit_dir/$unit.d" ]]; then
        echo 'Test unit has an existing drop-in directory' >&2; exit 1
    fi
done
for account in "$builder" "$app" "$deploy"; do
    if getent passwd "$account" >/dev/null || getent group "$account" >/dev/null; then
        echo 'Test account or group already exists' >&2; exit 1
    fi
done
existing=$(systemctl list-units --all --no-legend --plain --no-pager "$unit" "${prefix}-*.service")
[[ -z "${existing//[[:space:]]/}" ]] || { echo 'Test unit prefix already exists' >&2; exit 1; }
jobs=$(systemctl list-jobs --no-legend --plain --no-pager)
while read -r _ candidate _; do
    if [[ "$candidate" == "$unit" || "$candidate" == "${prefix}"-*.service ]]; then
        echo 'Test unit has pending job' >&2; exit 1
    fi
done <<< "$jobs"
for group in /sys/fs/cgroup/system.slice/"$unit" /sys/fs/cgroup/system.slice/"${prefix}"-*.service; do
    [[ ! -d "$group" ]] || { echo 'Test cgroup already exists' >&2; exit 1; }
done
mountpoint=$(mktemp -d /run/travel-pipeline-test.XXXXXXXX)
made_builder=0; made_app=0; made_deploy=0; mounted=0; unit_created=0; unit_create_started=0; unit_identity=''
cleanup_account() {
    local account=$1 created=$2
    (( created )) || return 0
    userdel "$account" || { echo "WARNING: remove $account manually" >&2; return 1; }
    if getent group "$account" >/dev/null; then
        groupdel "$account" || { echo "WARNING: remove group $account" >&2; return 1; }
    fi
}
cleanup() {
    local unsafe=0 cleanup_failed=0 listing jobs candidate load active sub rest group result fragment
    if ! listing=$(systemctl list-units --all --no-legend --plain --no-pager "$unit" "${prefix}-*.service"); then
        unsafe=1; listing=''
    fi
    while read -r candidate load active sub rest; do
        [[ "$candidate" == "$unit" || "$candidate" == "${prefix}"-*.service ]] || continue
        if [[ "$candidate" == "$unit" ]]; then
            if ! fragment=$(systemctl show "$unit" -p FragmentPath --value) || [[ "$fragment" != "$unit_file" ]]; then
                echo "WARNING: unexpected unit source for $unit; refusing stop" >&2
                unsafe=1; continue
            fi
        fi
        systemctl stop "$candidate" || unsafe=1
    done <<< "$listing"
    if ! jobs=$(systemctl list-jobs --no-legend --plain --no-pager); then unsafe=1; jobs=''; fi
    while read -r _ candidate rest; do
        if [[ "$candidate" == "$unit" || "$candidate" == "${prefix}"-*.service ]]; then
            if [[ "$candidate" == "$unit" ]]; then
                if ! fragment=$(systemctl show "$unit" -p FragmentPath --value) || [[ "$fragment" != "$unit_file" ]]; then
                    echo "WARNING: unexpected unit source for $unit; refusing stop" >&2
                    unsafe=1; continue
                fi
            fi
            systemctl stop "$candidate" || unsafe=1
        fi
    done <<< "$jobs"
    if ! jobs=$(systemctl list-jobs --no-legend --plain --no-pager); then unsafe=1; jobs=''; fi
    while read -r _ candidate rest; do
        if [[ "$candidate" == "$unit" || "$candidate" == "${prefix}"-*.service ]]; then unsafe=1; fi
    done <<< "$jobs"
    if ! listing=$(systemctl list-units --all --no-legend --plain --no-pager "$unit" "${prefix}-*.service"); then
        unsafe=1; listing=''
    fi
    while read -r candidate load active sub rest; do
        [[ "$candidate" == "$unit" || "$candidate" == "${prefix}"-*.service ]] || continue
        [[ "$active" == inactive || "$active" == failed ]] || unsafe=1
    done <<< "$listing"
    for group in /sys/fs/cgroup/system.slice/"$unit" /sys/fs/cgroup/system.slice/"${prefix}"-*.service; do
        [[ -d "$group" ]] || continue
        if [[ ! -r "$group/cgroup.events" ]] || ! grep -qx 'populated 0' "$group/cgroup.events"; then unsafe=1; fi
    done
    for account in "$builder" "$app"; do
        if getent passwd "$account" >/dev/null; then
            if pgrep -u "$account" >/dev/null; then unsafe=1; else result=$?; (( result == 1 )) || unsafe=1; fi
        fi
    done
    if (( unsafe )); then
        echo "WARNING: preserving mount $mountpoint and accounts $builder $app $deploy; processes not proven stopped" >&2
        return 1
    fi
    if (( unit_created )); then
        if [[ ! -f "$unit_file" || -L "$unit_file" ]] || [[ "$(stat -c '%d:%i' "$unit_file")" != "$unit_identity" ]]; then
            echo "WARNING: test unit identity changed; preserving $unit_file, mount and accounts" >&2
            return 1
        fi
        if ! rm -- "$unit_file"; then echo "WARNING: remove $unit_file manually" >&2; return 1; fi
        if ! systemctl daemon-reload; then
            echo "WARNING: daemon-reload failed; preserving mount $mountpoint and accounts" >&2; return 1
        fi
    elif (( unit_create_started )) && [[ -e "$unit_file" || -L "$unit_file" ]]; then
        echo "WARNING: unverified unit file $unit_file; preserving mount and accounts" >&2
        return 1
    fi
    if (( mounted )) && ! umount "$mountpoint"; then echo "WARNING: unmount $mountpoint manually" >&2; return 1; fi
    rmdir "$mountpoint" || { echo "WARNING: remove $mountpoint manually" >&2; cleanup_failed=1; }
    cleanup_account "$deploy" "$made_deploy" || cleanup_failed=1
    cleanup_account "$app" "$made_app" || cleanup_failed=1
    cleanup_account "$builder" "$made_builder" || cleanup_failed=1
    return "$cleanup_failed"
}
trap cleanup EXIT
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$builder"; made_builder=1
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$app"; made_app=1
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$deploy"; made_deploy=1
chown root:root "$work"; chmod 0755 "$work"
mount --bind "$work" "$mountpoint"; mounted=1
mkdir -m 0755 "$mountpoint/tools"
install -m 0644 "$repo/deploy/server/deploy_pipeline.py" "$repo/deploy/server/receive_artifact.py" \
    "$repo/deploy/server/artifact_stream.py" "$repo/deploy/server/release_builder.py" \
    "$repo/deploy/server/release_tree.py" "$repo/deploy/server/release_build_worker.py" \
    "$repo/deploy/server/deployment_controller.py" "$repo/deploy/server/deployment_transaction.py" \
    "$repo/deploy/server/deployment_health.py" "$repo/deploy/server/integration_http_service.py" \
    "$repo/deploy/server/integration_pipeline.py" "$repo/deploy/server/create_pipeline_test_unit.py" "$mountpoint/tools/"
install -m 0755 "$repo/scripts/validate_artifact.py" "$repo/scripts/extract_artifact.py" "$mountpoint/tools/"
port=$(/usr/bin/python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
unit_create_started=1
unit_identity=$(/usr/bin/python3 -B "$mountpoint/tools/create_pipeline_test_unit.py" "$unit_file" "$mountpoint" "$app" "$port")
unit_created=1
systemctl daemon-reload
fragment=$(systemctl show "$unit" -p FragmentPath --value)
[[ "$fragment" == "$unit_file" ]] || { echo 'Unexpected test unit source' >&2; exit 1; }
/usr/bin/python3 -B "$mountpoint/tools/integration_pipeline.py" "$mountpoint" "$builder" "$app" "$deploy" "$unit" "$prefix" "$port" "$3"
if cleanup; then
    trap - EXIT
    if [[ "$3" == '--recovery-only' ]]; then echo 'RECOVERY_INTEGRATION_OK'; else echo 'PIPELINE_INTEGRATION_OK'; fi
else
    trap - EXIT
    echo 'ERROR: test scenarios completed but safe cleanup was not confirmed' >&2
    exit 1
fi
