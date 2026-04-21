#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OS="$(uname -s)"

case "${OS}" in
  Darwin)
    exec "${ROOT_DIR}/scripts/build-macos.sh" "$@"
    ;;
  Linux)
    echo "No dedicated Linux desktop target is configured yet. Use macOS or Windows build scripts." >&2
    exit 1
    ;;
  *)
    echo "Unsupported host OS: ${OS}" >&2
    exit 1
    ;;
esac
