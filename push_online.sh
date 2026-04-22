#!/bin/bash
# Backward-compatible wrapper. Prefer scripts/deploy/push_online.sh.
set -e
exec "$(cd "$(dirname "$0")" && pwd)/scripts/deploy/push_online.sh" "$@"
