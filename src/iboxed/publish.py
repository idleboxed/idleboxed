"""Publish all assets through a draft GitHub Release."""

import json
import logging
from pathlib import Path
from typing import Any

from .config import BundleError
from .process import run

logger = logging.getLogger(__name__)


def publish_bundle(root: Path, config: dict[str, Any]) -> str:
    """Upload the validated bundle to its GitHub release and return the release URL."""
    version = config["version"]
    output = root / "out" / version
    manifest = json.loads((output / "release.json").read_text())
    commit = run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()

    if manifest["config"] != config or manifest["integration_commit"] != commit:
        raise BundleError("Source or config changed since the build")

    if run(["git", "status", "--porcelain"], cwd=root).stdout.strip():
        raise BundleError("Commit source and config changes before publishing")

    names = manifest["assets"]

    if sorted(path.name for path in output.iterdir()) != names:
        raise BundleError("Missing or unexpected release assets")

    origin = run(["git", "remote", "get-url", "origin"], cwd=root).stdout.strip()
    repository = run(
        ["gh", "repo", "view", origin, "--json", "nameWithOwner", "--jq", ".nameWithOwner"], cwd=root,
    ).stdout.strip()
    tag = f"v{version}"
    endpoint = f"repos/{repository}/releases/tags/{tag}"
    existing = run(["gh", "api", endpoint], cwd=root, check=False)

    if existing.returncode == 0 or "HTTP 404" not in existing.stderr:
        raise BundleError("Release exists or could not be inspected; choose a new version or inspect its draft")

    local = run(["git", "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"], cwd=root, check=False)

    if local.returncode:
        run(["git", "tag", tag, commit], cwd=root)

    elif local.stdout.strip() != commit:
        raise BundleError("Tag points to another commit; tags are never moved")

    run(["git", "push", "origin", f"refs/tags/{tag}"], cwd=root)
    argv = [
        "gh", "release", "create", tag, "--repo", repository, "--verify-tag", "--draft",
        "--title", f"iboxed {version}", "--target", commit,
        "--notes", "Choose a platform and standard/diag archive. Component versions: release.json. "
        "Trampoline installation: https://github.com/idleboxed/itrampoline/blob/main/docs/usage.md",
        *(f"{output / name}" for name in names),
    ]

    if manifest["mode"] == "latest":
        argv.append("--prerelease")

    run(argv, cwd=root)
    draft = json.loads(run(["gh", "api", endpoint], cwd=root).stdout)
    sizes = {name: (output / name).stat().st_size for name in names}

    if not draft["draft"] or {asset["name"]: asset["size"] for asset in draft["assets"]} != sizes:
        raise BundleError("Draft assets are incomplete; inspect the draft before retrying")

    run(["gh", "release", "edit", tag, "--repo", repository, "--draft=false"], cwd=root)
    logger.info("Published %s", draft["html_url"])
    return draft["html_url"]
