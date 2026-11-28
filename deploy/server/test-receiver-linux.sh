#!/bin/bash
set -euo pipefail
if (( $# != 1 )); then echo 'Usage: bash test-receiver-linux.sh /path/to/repo' >&2; exit 2; fi
repo=$(realpath "$1")
base="$HOME/travel-deploy-test"
mkdir -p "$base"
work=$(mktemp -d "$base/receiver-test-XXXXXXXX")
echo "Running with sudo in isolated test directory: $work"
sudo /usr/bin/python3 "$repo/deploy/server/integration_receiver.py" "$work" "$repo" "$(id -un)"
echo "Inspect and remove only this test directory when finished: sudo rm -r -- '$work'"
