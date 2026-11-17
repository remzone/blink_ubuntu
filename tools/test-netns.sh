#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export BLINK_HOST_NETNS="$(readlink /proc/self/ns/net)"
export BLINK_NETNS_TEST=1
unshare --user --map-root-user --net go test -ldflags=-checklinkname=0 ./internal/network -run TestIsolated -count=1 -v
