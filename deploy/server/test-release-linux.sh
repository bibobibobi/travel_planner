#!/bin/bash
# This script creates isolated system accounts and a temporary bind mount.
set -euo pipefail
if (( $# < 1 || $# > 2 )) || [[ "${2:-}" != '' && "${2:-}" != '--cgroup-only' ]]; then
    echo 'Usage: bash test-release-linux.sh /path/to/repository [--cgroup-only]' >&2; exit 2
fi
repo=$(realpath "$1")
base="$HOME/travel-deploy-test"
mkdir -p "$base"
work=$(mktemp -d "$base/release-integration-XXXXXXXX")
echo "Native Linux test directory: $work"
echo 'sudo is needed for isolated test accounts, transient systemd services and a temporary bind mount.'
sudo /bin/bash "$repo/deploy/server/test-release-root.sh" "$work" "$repo" "${2:-}"
echo "Inspect and remove only this test directory when finished: sudo rm -r -- '$work'"
