#!/bin/bash
set -euo pipefail
if (( $# != 1 )); then echo 'Usage: bash test-entry-linux.sh /path/to/repo' >&2; exit 2; fi
repo=$(realpath "$1")
for file in travel-deploy-entry.candidate travel-deploy-control.candidate receive-wrapper; do
    bash -n "$repo/deploy/server/$file"
done
/usr/sbin/visudo -cf "$repo/deploy/server/sudoers.candidate"
/usr/bin/python3 "$repo/deploy/server/test_entry_linux.py" "$repo"
echo 'sudo endpoint was simulated; installed sudo policy and root receiver were not exercised.'
