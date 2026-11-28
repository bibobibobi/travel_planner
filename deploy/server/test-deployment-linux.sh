#!/bin/bash
set -euo pipefail
if (( $# != 1 )); then echo 'Usage: bash test-deployment-linux.sh /path/to/repo' >&2; exit 2; fi
repo=$(realpath "$1")
base="$HOME/travel-deploy-test"
mkdir -p "$base"
work=$(mktemp -d "$base/deployment-test-XXXXXXXX")
echo "Native Linux test directory: $work"
echo 'sudo is required for isolated accounts, a bind mount and a randomly named systemd service.'
sudo /bin/bash "$repo/deploy/server/test-deployment-root.sh" "$work" "$repo"
echo "Inspect and remove only this directory when finished: sudo rm -r -- '$work'"
