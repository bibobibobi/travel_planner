#!/bin/bash
# Reference fragment only; merge before the existing command regex. This is not
# an SSH forced command and deliberately does not alter the existing entry.
if [[ "${COMMAND:-}" =~ ^deploy-artifact\ ([0-9a-f]{40})\ ([0-9a-f]{64})$ ]]; then
    revision="${BASH_REMATCH[1]}"
    digest="${BASH_REMATCH[2]}"
    { printf '%s %s\n' "$revision" "$digest"; /usr/bin/cat; } |
        /usr/bin/sudo -n /usr/local/sbin/travel-receive-wrapper
    exit "$?"
fi
