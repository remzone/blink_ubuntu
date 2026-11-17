#!/usr/bin/env bash
# Source only for this checkout's isolated build caches.
BLINK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export GOPATH="$BLINK_ROOT/work/gopath" GOCACHE="$BLINK_ROOT/work/gocache" GOMODCACHE="$BLINK_ROOT/work/gomod" GOTMPDIR="$BLINK_ROOT/work/tmp" TMPDIR="$BLINK_ROOT/work/tmp"
mkdir -p "$GOPATH" "$GOCACHE" "$GOMODCACHE" "$GOTMPDIR"
if [ -x "$BLINK_ROOT/work/toolchain/go/bin/go" ]; then export PATH="$BLINK_ROOT/work/toolchain/go/bin:$PATH"; fi

if [ ! -f "$BLINK_ROOT/work/go.mod" ]; then printf "module blink-local-work\n\ngo 1.27.0\n" > "$BLINK_ROOT/work/go.mod"; fi
