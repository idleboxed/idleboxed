"""The approved build and publish commands."""

import argparse
import logging
from pathlib import Path

from .build import build_bundle
from .config import BundleError, read_config
from .publish import publish_bundle

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Run the selected bundle command and return its exit code."""
    parser = argparse.ArgumentParser(prog="iboxed", description="Build and publish Idle bundles")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Build config.toml from pinned components")
    build.add_argument("--latest", action="store_true", help="Freeze current component main branches")
    commands.add_parser("publish", help="Publish the built bundle through gh")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        root = Path.cwd()
        config = read_config(root)

        if args.command == "build":
            build_bundle(root, config, latest=args.latest)

        else:
            publish_bundle(root, config)

    except KeyboardInterrupt:
        logger.error("Cancelled; inspect build reports or the release draft before retrying")
        return 130

    except (BundleError, OSError, ValueError, KeyError, TypeError) as exc:
        logger.error("%s", exc)
        return 1

    return 0
