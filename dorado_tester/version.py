from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from .dorado_commands import version_command

# Matches e.g. "1.0.2" or "1.0.2+abc1234"
_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+(?:\+[0-9a-zA-Z]+)?)")


@dataclass
class DoradoVersion:
    raw: str
    safe: str


def get_dorado_version(dorado_path: str) -> DoradoVersion:
    result = subprocess.run(
        version_command(dorado_path),
        capture_output=True,
        text=True,
        check=False,
    )
    # Some builds print the version to stderr, so both streams are scanned.
    combined = (result.stdout or "") + (result.stderr or "")
    match = _VERSION_RE.search(combined)
    if not match:
        raise RuntimeError(f"Could not parse Dorado version from output: {combined!r}")
    raw = match.group(1)
    safe = re.sub(r"[^A-Za-z0-9.+_-]", "_", raw)
    return DoradoVersion(raw=raw, safe=safe)
