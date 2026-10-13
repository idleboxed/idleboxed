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
    revisions = {}

    for name in COMPONENTS:
        source = root / "components" / name

        if latest:
            run(["git", "fetch", "--no-tags", "origin", "main"], cwd=source)

        ref = "FETCH_HEAD" if latest else "HEAD"
        revisions[name] = run(["git", "rev-parse", ref], cwd=source).stdout.strip()

    created = []
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

    finally:

        for name in reversed(created):
            run(["git", "worktree", "remove", "--force", f"{destination / name}"],
                cwd=root / "components" / name)


def build_bundle(root: Path, config: dict[str, Any], *, latest: bool = False) -> Path:
    version = config["version"]
    output = root / "out" / version

    if output.exists():
        raise BundleError(f"Bundle already exists: {output}; choose a new version")

    if run(["git", "status", "--porcelain"], cwd=root).stdout.strip():
        raise BundleError("Commit source and config changes before building")

    commit = run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="iboxed-") as temporary:
        stage = Path(temporary)
        assets = stage / "assets"
        assets.mkdir()
        source_root = stage / "sources"
        source_root.mkdir()
        builds = []

        with freeze_sources(root, source_root, latest=latest) as sources:

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

                    archive = f"iboxed-{version}-{name}-{variant}.tar.gz"

                    with tarfile.open(assets / archive, "w:gz") as package:

                        for relative in ("system", "INSTRUCTIONS.md", "games/states", "games/saves"):
                            package.add(destination / relative, arcname=relative)

                        package.add(root / "THIRD_PARTY.txt", arcname="THIRD_PARTY.txt")

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
                        "platform": name, "variant": variant, "archive": archive, "components": components,
                        "shader": {key: shader[key] for key in ("repository", "revision") if key in shader},
                    })

        shutil.copyfile(root / "THIRD_PARTY.txt", assets / "THIRD_PARTY.txt")
        manifest = {
            "version": version, "integration_commit": commit, "config": config,
            "mode": "latest" if latest else "pinned", "sources": sources, "builds": builds,
            "assets": sorted([path.name for path in assets.iterdir()] + ["release.json"]),
        }
        (assets / "release.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        shutil.move(assets, output)

    logger.info("Bundle ready: %s", output)
    return output
