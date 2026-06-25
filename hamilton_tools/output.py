from __future__ import annotations

import json
import sys
from typing import Any


def emit_json(data: Any) -> None:
    json.dump(data, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
