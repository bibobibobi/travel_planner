#!/bin/bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "$0")" && pwd)
definition=$(sed -n '/^cleanup() {/,/^}$/p' "$script_dir/test-backup-root.sh")
[[ -n $definition ]]
for status in 0 2; do
    output=$(
        /bin/bash -c '
          created_users=(test1 test2); created_group=1; mounted=1
          group=testgroup; mount_dir=/test-mount; work=/test-work
          # Simulate one safe account followed by one unsafe/unknown account.
          userdel() { echo UNEXPECTED_USERDEL; }
          groupdel() { echo UNEXPECTED_GROUPDEL; }
          umount() { echo UNEXPECTED_UMOUNT; }
          rmdir() { echo UNEXPECTED_RMDIR; }
          TEST_PROBE=$2
          pgrep() { [[ $2 == test1 ]] && return 1; return "$TEST_PROBE"; }
          eval "$1"
          cleanup
        ' test "$definition" "$status" 2>&1
    ) && { echo "Unsafe probe $status unexpectedly succeeded" >&2; exit 1; }
    [[ $output == *"preserving all test resources"* && $output != *UNEXPECTED_* ]] || {
        echo "Unsafe cleanup behavior: $output" >&2; exit 1;
    }
done
echo BACKUP_CLEANUP_TEST_OK
