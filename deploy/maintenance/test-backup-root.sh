#!/bin/bash
set -Eeuo pipefail
trap 'rc=$?; echo "Backup test failed at line $LINENO (exit $rc)" >&2' ERR
[[ $EUID == 0 && -n ${SUDO_USER:-} ]] || { echo 'Run through test-backup-linux.sh using sudo' >&2; exit 1; }
for cmd in /usr/bin/getfacl /usr/sbin/useradd /usr/sbin/groupadd /usr/sbin/runuser /usr/sbin/visudo; do
    [[ -x $cmd ]] || { echo "Missing required program: $cmd" >&2; exit 1; }
done
repo=$(realpath "$1")
/usr/sbin/visudo -cf "$repo/deploy/maintenance/sudoers.server-backup-additions"
home=$(getent passwd "$SUDO_USER" | cut -d: -f6)
[[ -d "$home" && "$home" != /mnt/* ]] || { echo 'Linux native home required' >&2; exit 1; }
base="$home/travel-deploy-test"
mkdir -p -- "$base"
work=$(mktemp -d "$base/backup-test-XXXXXXXX")
chmod 755 "$work"
tag=$(basename "$work" | tr '[:upper:]' '[:lower:]' | cut -c13-20)
group="tbg${tag}"; backup="tbb${tag}"; deploy="tbd${tag}"; build="tbu${tag}"; app="tba${tag}"
created_group=0
created_users=()
mount_dir=$(mktemp -d /run/travel-backup-test.XXXXXXXX)
mounted=0
cleanup() {
    local rc=$? account probe unsafe=0
    trap - EXIT ERR
    for account in "${created_users[@]}"; do
        if pgrep -u "$account" >/dev/null; then probe=0; else probe=$?; fi
        if (( probe != 1 )); then
            echo "Cannot prove account $account has no processes (pgrep=$probe); preserving all test resources" >&2
            unsafe=1
        fi
    done
    if (( unsafe )); then
        echo "Test resources retained: accounts=${created_users[*]} group=$group mount=$mount_dir files=$work" >&2
        exit 1
    fi
    for account in "${created_users[@]}"; do
        if ! userdel "$account"; then
            echo "Could not remove test account $account; preserving remaining resources" >&2
            exit 1
        fi
    done
    if (( created_group )) && ! groupdel "$group"; then
        echo "Could not remove test group $group" >&2; rc=1
    fi
    if (( mounted )); then
        if ! umount -- "$mount_dir"; then
            echo "Could not unmount $mount_dir; preserve for manual inspection" >&2; rc=1
        else
            mounted=0
        fi
    fi
    if (( ! mounted )); then rmdir -- "$mount_dir" || rc=1; fi
    echo "Test files retained for inspection: $work" >&2
    if (( rc == 0 )); then echo BACKUP_INTEGRATION_OK; fi
    exit "$rc"
}
trap cleanup EXIT
mount --bind "$work" "$mount_dir"; mounted=1
groupadd "$group"; created_group=1
for account in "$backup" "$deploy" "$build" "$app"; do
    useradd --system --user-group --no-create-home --shell /usr/sbin/nologin "$account"
    created_users+=("$account")
done
usermod -a -G "$group" "$backup"
/usr/bin/python3 "$repo/deploy/maintenance/integration_backup.py" "$repo" "$mount_dir" "$group" "$backup" "$deploy" "$build" "$app"
