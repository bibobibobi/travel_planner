#!/bin/bash
set -Eeuo pipefail
repo=$(realpath "${1:-.}")
[[ -f "$repo/deploy/maintenance/backup.sh" ]] || { echo 'Repository not found' >&2; exit 1; }
[[ "$repo" != /mnt/* ]] || { echo 'Use a WSL native Linux filesystem' >&2; exit 1; }
command -v sudo >/dev/null
sudo /bin/bash "$repo/deploy/maintenance/test-backup-root.sh" "$repo"
