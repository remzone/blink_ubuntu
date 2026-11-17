#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 tools/verify-native.py
go test -race -ldflags=-checklinkname=0 ./cmd/... ./internal/...
(cd native && go test -race -ldflags=-checklinkname=0 ./...)
/usr/bin/python3 -m unittest discover -s tests -v
