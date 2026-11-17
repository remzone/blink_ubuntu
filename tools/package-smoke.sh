#!/usr/bin/env bash
# Run as root ONLY in an isolated container. No host network changes.
set -euo pipefail
[ -f /.dockerenv ] || { echo "Run only in a disposable Docker container" >&2; exit 1; }
cd /project
export DEBIAN_FRONTEND=noninteractive
export PYTHONDONTWRITEBYTECODE=1
trap 'chown -R "$(stat -c "%u:%g" /project)" /project/work/session-smoke 2>/dev/null || true' EXIT
apt-get update -qq
apt-get install -y -qq ./dist/blink-ubuntu_0.2.1_amd64.deb xvfb xauth >/dev/null
/usr/bin/blink version
xvfb-run -a /usr/bin/python3 -m unittest discover -s tests -v
# systemd is not PID 1 in this container; substitute only resolved's external
# command for lifecycle tests. Real resolver integration needs a desktop VM.
printf '#!/bin/sh\nexit 0\n' > /usr/bin/resolvectl
chmod 755 /usr/bin/resolvectl
/usr/bin/python3 tools/session-smoke.py
