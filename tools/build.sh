#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dist
export CGO_ENABLED=0
export GOOS=linux
export GOAMD64=v1
# The pinned Xray QUIC dependency uses an internal TLS symbol.
go build -trimpath -ldflags='-s -w -checklinkname=0' -o dist/blink ./cmd/blink
python3 tools/package.py
