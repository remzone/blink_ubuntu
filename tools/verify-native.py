#!/usr/bin/env python3
"""Check the vendored snapshot against its committed SHA-256 manifest."""
import hashlib
import json
from pathlib import Path
root = Path(__file__).resolve().parent.parent
expected = json.loads((root / "docs/native-manifest.json").read_text())
actual = {str(p.relative_to(root / "native")): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sorted((root / "native").rglob("*")) if p.is_file()}
if actual != expected:
    raise SystemExit("Native snapshot changed; review provenance and regenerate manifest intentionally")
print("Native snapshot: {} files verified".format(len(actual)))
