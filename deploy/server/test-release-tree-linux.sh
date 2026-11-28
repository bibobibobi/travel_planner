#!/bin/bash
# Tests only the copy primitive; this does not build or publish a release.
set -euo pipefail
if (( $# != 1 )); then echo 'Usage: bash test-release-tree-linux.sh /path/to/repo' >&2; exit 2; fi
repo=$(realpath "$1")
base="$HOME/travel-deploy-test"
mkdir -p "$base"
work=$(mktemp -d "$base/release-tree-test-XXXXXXXX")
echo "Isolated test directory: $work"
cd "$repo"
"$repo/.venv/bin/python" -m pytest -q tests/test_release_tree.py --basetemp "$work/pytest"
echo "Inspect and remove only this test directory when finished: rm -r -- '$work'"
