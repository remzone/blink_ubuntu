#!/usr/bin/env python3
"""Build a reproducible-layout Debian package without installing anything."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent.parent
VERSION = "0.2.1"
arch = os.environ.get("GOARCH", "amd64")
if arch not in ("amd64", "arm64"):
    raise SystemExit("Supported package architectures: amd64, arm64")
binary_source = os.environ.get("BLINK_PACKAGE_BINARY", "dist/blink")
header = (ROOT / binary_source).read_bytes()[:20]
expected_machine = {"amd64": 62, "arm64": 183}[arch]
if header[:4] != b"\x7fELF" or int.from_bytes(header[18:20], "little") != expected_machine:
    raise SystemExit("Binary architecture does not match package architecture")
stage = ROOT / "dist" / ("package-" + arch)
if stage.exists():
    shutil.rmtree(stage)

def copy(source, dest, mode=0o644):
    target = stage / dest
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / source, target)
    target.chmod(mode)

copy(binary_source, "usr/bin/blink", 0o755)
for name in ("blink_gui.py", "theme.py", "captcha_protocol.py", "captcha_window.py", "captcha_shell.js", "vendor/vkid-captcha-2.0.0.js", "vendor/VKID-CAPTCHA-LICENSE"):
    copy("gui/" + name, "usr/share/blink/" + name, 0o755 if name in ("blink_gui.py", "captcha_window.py") else 0o644)
copy("packaging/blink.desktop", "usr/share/applications/blink.desktop")
copy("packaging/blink.svg", "usr/share/icons/hicolor/scalable/apps/blink.svg")
copy("packaging/org.remzone.blink.policy", "usr/share/polkit-1/actions/org.remzone.blink.policy")
for doc in ("README.md", "LICENSE", "docs/ARCHITECTURE.md", "docs/COMPATIBILITY.md", "docs/PROVENANCE.md", "docs/VALIDATION.md", "docs/CAPTCHA.md", "docs/UI-DESIGN.md"):
    copy(doc, "usr/share/doc/blink-ubuntu/" + Path(doc).name)
for component in ("share", "vkturn", "resources"):
    copy("native/" + component + "/LICENSE", "usr/share/doc/blink-ubuntu/licenses/" + component + "-LICENSE")
    notice = ROOT / "native" / component / "UPSTREAM.md"
    if notice.exists():
        copy(str(notice.relative_to(ROOT)), "usr/share/doc/blink-ubuntu/licenses/" + component + "-UPSTREAM.md")
control = stage / "DEBIAN"
control.mkdir()
(control / "control").write_text("""Package: blink-ubuntu
Version: {version}
Section: net
Priority: optional
Architecture: {arch}
Maintainer: Remzone <remziesh@icloud.com>
Depends: ca-certificates, iproute2, python3 (>= 3.8), python3-tk, python3-gi, python3-pil, gir1.2-gtk-3.0, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0, sudo, pkexec | policykit-1, systemd-resolved | systemd (<< 252)
Homepage: https://github.com/remzone/blink_ubuntu
Description: Blink VPN client for Ubuntu 20.04 and later
 Console and graphical client based on the Blink iOS and Android Go core.
 Supports Xray profiles, WireGuard, AmneziaWG and Vokop TURN subscriptions.
""".format(version=VERSION, arch=arch))
package = ROOT / "dist" / ("blink-ubuntu_{}_{}.deb".format(VERSION, arch))
subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(package)], check=True)
archive = ROOT / "dist" / ("blink-ubuntu_{}_{}.tar.gz".format(VERSION, arch))
with tarfile.open(archive, "w:gz") as tar:
    for item in (binary_source, "gui", "packaging", "README.md", "LICENSE", "docs"):
        tar.add(ROOT / item, arcname="blink" if item == binary_source else item,
                filter=lambda info: None if "__pycache__" in info.name else info)
for artifact in (package, archive):
    artifact.with_suffix(artifact.suffix + ".sha256").write_text(hashlib.sha256(artifact.read_bytes()).hexdigest() + "  " + artifact.name + "\n")
print(package)
print(archive)
