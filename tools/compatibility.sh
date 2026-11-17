#!/usr/bin/env bash
# Execute inside a disposable Ubuntu container with this checkout at /project.
set -euo pipefail
[ -f /.dockerenv ] || { echo "Run only in a disposable Docker container" >&2; exit 1; }
cd /project
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
webkit_package=gir1.2-webkit2-4.0
if apt-cache show gir1.2-webkit2-4.1 >/dev/null 2>&1; then webkit_package=gir1.2-webkit2-4.1; fi
apt-get install -y -qq python3 python3-tk python3-gi python3-pil gir1.2-gtk-3.0 "$webkit_package" xvfb xauth iproute2 ca-certificates >/dev/null
export BLINK_WEBKIT_TEST=1 LIBGL_ALWAYS_SOFTWARE=1
# Only for root tests inside the disposable Docker container, never in Blink.
export WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1
export PYTHONDONTWRITEBYTECODE=1
export XDG_CONFIG_HOME=/project/work/compat-"${BLINK_UBUNTU_VERSION:-unknown}"
trap 'chown -R "$(stat -c "%u:%g" /project)" "$XDG_CONFIG_HOME"' EXIT
./dist/blink version
./dist/blink import --file fixtures/standard-subscription.txt
./dist/blink list
xvfb-run -a /usr/bin/python3 -m unittest discover -s tests -v
