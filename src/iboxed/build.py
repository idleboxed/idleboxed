"""Freeze component revisions, call iroll and package its clean output."""

import json
import logging
import shutil
import sys
import tarfile
import tempfile
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import BundleError
from .process import run

logger = logging.getLogger(__name__)
COMPONENTS = ("iroll", "iman", "igui", "imanlib")
IROLL_SCRIPT = """
import sys
sys.path.insert(0, sys.argv[1])
from iroll.cli import main
raise SystemExit(main(sys.argv[2:]))
"""


@contextmanager
def freeze_sources(root: Path, destination: Path, *, latest: bool) -> Iterator[dict[str, Any]]:
    """Check out fixed component revisions and remove every checkout on exit."""
    revisions = {}

    for name in COMPONENTS:
        source = root / "components" / name

        if latest:
            run(["git", "fetch", "--no-tags", "origin", "main"], cwd=source)

        ref = "FETCH_HEAD" if latest else "HEAD"
        revisions[name] = run(["git", "rev-parse", ref], cwd=source).stdout.strip()

    created = []
    primary_error: BaseException | None = None
    try:
        sources = {}

        for name, commit in revisions.items():
            checkout = destination / name
            run(["git", "worktree", "add", "--detach", f"{checkout}", commit], cwd=root / "components" / name)
            created.append(name)
            python = name == "iroll"
            manifest = checkout / ("pyproject.toml" if python else "Cargo.toml")
            package = tomllib.loads(manifest.read_text())["project" if python else "package"]
            sources[name] = {"commit": commit, "version": package["version"]}

            if name in ("iman", "igui"):
                lock = tomllib.loads((checkout / "Cargo.lock").read_text())
                sources[name]["imanlib"] = [
                    {key: dependency[key] for key in ("version", "source")}
                    for dependency in lock["package"] if dependency["name"] == "imanlib"
                ]

        yield sources

    except BaseException as error:
        primary_error = error
        raise

    finally:
        cleanup_errors = []

        for name in reversed(created):
            checkout = destination / name
            try:
                run(["git", "worktree", "remove", "--force", f"{checkout}"], cwd=root / "components" / name)

            except BaseException as error:
                # A failed removal must not leave later worktrees unattempted,
                # nor replace the build error or cancellation that brought us here.
                detail = f"Could not remove worktree {checkout}: {error}"
                logger.error("%s", detail)
                cleanup_errors.append(error)

                if primary_error is not None:
                    primary_error.add_note(detail)

        if cleanup_errors and primary_error is None:
            first_error = cleanup_errors[0]

            for error in cleanup_errors[1:]:
                first_error.add_note(f"Additional worktree cleanup failure: {error}")

            raise first_error


def _validate_output(root: Path, version: str) -> Path:

    if (not isinstance(version, str) or not version or version in (".", "..")
            or Path(version).name != version or "\\" in version or "\x00" in version):
        raise BundleError("Bundle version must be a single directory name")

    output = root / "out" / version

    for path in (output.parent, output):

        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise BundleError(f"Bundle output must be a directory, not a symlink or other file: {path}")

    return output


def build_bundle(root: Path, config: dict[str, Any], *, latest: bool = False) -> Path:
    """Build each configured variant and publish its archives only after packaging succeeds."""
    version = config["version"]
    output = _validate_output(root, version)

    if run(["git", "status", "--porcelain"], cwd=root).stdout.strip():
        raise BundleError("Commit source and config changes before building")

    commit = run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()

    with tempfile.TemporaryDirectory(prefix="iboxed-") as temporary:
        stage = Path(temporary)
        assets = stage / "assets"
        assets.mkdir()
        source_root = stage / "sources"
        source_root.mkdir()
        builds = []

        with freeze_sources(root, source_root, latest=latest) as sources:
            _validate_output(root, version)
            output.parent.mkdir(parents=True, exist_ok=True)

            if output.exists():
                logger.info("Removing previous bundle: %s", output)
                shutil.rmtree(output)

            for platform in config["platforms"]:

                for variant in platform["variants"]:
                    name = platform["name"]
                    target = stage / f"{name}-{variant}"
                    target.mkdir()
                    destination = target / "sd"
                    source_package = source_root / "iroll/src"
                    argv = [
                        sys.executable, "-I", "-c", IROLL_SCRIPT, f"{source_package}", "rollout",
                        "--platform", name, "--source", f"{source_root}", "--dest", f"{destination}",
                        "--bios", f"{target / "no-bios"}",
                        "--with-igui", "--with-iman", "--with-retro", "--with-cores", "--json",
                    ]

                    if variant == "standard":
                        argv.append("--no-diag")

                    logger.info("Building %s/%s", name, variant)
                    response = json.loads(run(argv, cwd=root).stdout)
                    report = json.loads((Path(response["reports"]) / "result.json").read_text())

                    components = {
                        component: {
                            "source": {key: value for key, value in record["source"].items() if key != "sha256"},
                            "files": sorted(record["files"]),
                            "submodules": [{"directory": module["directory"], "revision": module["source"]["revision"]}
                                           for module in record.get("submodules", [])],
                        } for component, record in report["components"].items()
                    }
                    shader = report.get("bundled_shader_source", {})
                    builds.append({
                        "platform": name, "variant": variant,
                        "archive": f"iboxed-{version}-{name}-{variant}.tar.gz", "components": components,
                        "shader": {key: shader[key] for key in ("repository", "revision") if key in shader},
                    })

        manifest = {
            "version": version, "integration_commit": commit, "config": config,
            "mode": "latest" if latest else "pinned", "sources": sources, "builds": builds,
            "assets": sorted([record["archive"] for record in builds] + ["release.json"]),
        }
        manifest_path = assets / "release.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        for record in builds:
            destination = stage / f"{record["platform"]}-{record["variant"]}" / "sd"
            archive = record["archive"]
            logger.info("Packaging %s", archive)

            with tarfile.open(assets / archive, "w:gz") as package:

                for relative in ("system", "INSTRUCTIONS.md", "games/states", "games/saves"):
                    package.add(destination / relative, arcname=relative)

                package.add(manifest_path, arcname="system/release.json")
                package.add(root / "THIRD_PARTY.txt", arcname="system/THIRD_PARTY.txt")

        _validate_output(root, version)

        if output.exists():
            raise BundleError(f"Bundle output appeared during the build: {output}")

        shutil.move(assets, output)

    logger.info("Bundle ready: %s", output)
    return output
