"""Read the bundle version and platform matrix."""

import re
import tomllib
from pathlib import Path
from typing import Any


class BundleError(Exception):
    """An expected build or publication error."""


def read_config(root: Path) -> dict[str, Any]:
    """Read config.toml and reject invalid versions, platforms or variants."""
    config = tomllib.loads((root / "config.toml").read_text(encoding="utf-8"))
    version = config.get("version", "")

    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", version):
        raise BundleError("version must be a bundle version such as 0.1.0")

    targets = [(platform["name"], variant) for platform in config["platforms"] for variant in platform["variants"]]

    if not targets or len(set(targets)) != len(targets):
        raise BundleError("Choose a nonempty matrix without duplicate targets")

    if any(name not in ("rk3032", "linux-x86_64") or variant not in ("standard", "diag")
           or (name == "linux-x86_64" and variant == "diag") for name, variant in targets):
        raise BundleError("Supported targets: rk3032 standard/diag, linux-x86_64 standard")

    return config
