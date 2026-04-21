#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="wowcoach"
OUTPUT_DIR="${ROOT_DIR}/build/macos"
ARCH="${1:-$(go env GOARCH)}"
VERSION="${VERSION:-$(git -C "${ROOT_DIR}" rev-parse --short HEAD 2>/dev/null || echo dev)}"

case "${ARCH}" in
  arm64|amd64)
    ;;
  *)
    echo "Unsupported macOS arch: ${ARCH}. Use arm64 or amd64." >&2
    exit 1
    ;;
esac

mkdir -p "${OUTPUT_DIR}"

echo "==> Verifying test suite"
(
  cd "${ROOT_DIR}"
  go test ./...
)

echo "==> Building ${APP_NAME} for macOS (${ARCH})"
(
  cd "${ROOT_DIR}"
  GOOS=darwin GOARCH="${ARCH}" go build \
    -tags production \
    -trimpath \
    -ldflags="-s -w -X main.Version=${VERSION}" \
    -o "${OUTPUT_DIR}/${APP_NAME}-${ARCH}" \
    .
)

echo "Built ${OUTPUT_DIR}/${APP_NAME}-${ARCH}"
