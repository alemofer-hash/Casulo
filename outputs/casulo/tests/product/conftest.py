from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
for relative in (
    "editions/casulo-public/src",
    "private/casulo-owner/src",
    "services/casulo-cloud-standby/src",
):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)
