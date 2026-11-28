#!/bin/bash
set -euo pipefail
if (( $# < 1 || $# > 2 )) || [[ "${2:-}" != '' && "${2:-}" != '--recovery-only' ]]; then
    echo 'Usage: bash test-pipeline-linux.sh /path/to/repo [--recovery-only]' >&2; exit 2
fi
repo=$(realpath "$1")
base="$HOME/travel-deploy-test"
mkdir -p "$base"
work=$(mktemp -d "$base/pipeline-test-XXXXXXXX")
echo "Native Linux test directory: $work"
if [[ "${2:-}" != '--recovery-only' ]]; then bash "$repo/deploy/server/test-entry-linux.sh" "$repo"; fi
echo 'sudo is required for isolated test accounts, systemd units and a temporary bind mount.'
sudo /bin/bash "$repo/deploy/server/test-pipeline-root.sh" "$work" "$repo" "${2:-}"
echo "Inspect and remove only this test directory when finished: sudo rm -r -- '$work'"
