#!/usr/bin/env bash
# Execute inside a disposable Ubuntu container with this checkout at /project.
set -euo pipefail
[ -f /.dockerenv ] || { echo "Run only in a disposable Docker container" >&2; exit 1; }
cd /project
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-tk xvfb xauth iproute2 ca-certificates >/dev/null
export PYTHONDONTWRITEBYTECODE=1
export XDG_CONFIG_HOME=/project/work/compat-"${BLINK_UBUNTU_VERSION:-unknown}"
trap 'chown -R "$(stat -c "%u:%g" /project)" "$XDG_CONFIG_HOME"' EXIT
./dist/blink version
./dist/blink import --file fixtures/standard-subscription.txt
./dist/blink list
xvfb-run -a /usr/bin/python3 -m unittest discover -s tests -v
