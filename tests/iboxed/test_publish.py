import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from iboxed import publish
from iboxed.config import BundleError


@pytest.mark.parametrize("mode,failure", [
    ("pinned", None), ("latest", None), ("pinned", "existing"),
    ("pinned", "upload"), ("pinned", "incomplete"), ("pinned", "tag"),
])
def test_publication_keeps_failures_unpublished_and_never_overwrites_assets(
    tmp_path: Path, config: dict[str, Any], monkeypatch: pytest.MonkeyPatch, mode: str, failure: str | None,
) -> None:
    output = tmp_path / "out/0.1.0"
    output.mkdir(parents=True)
    (output / "synthetic.tar.gz").write_bytes(b"Synthetic archive")
    names = ["release.json", "synthetic.tar.gz"]
    (output / "release.json").write_text(json.dumps({
        "version": "0.1.0", "config": config, "integration_commit": "a" * 40, "assets": names, "mode": mode,
    }))
    calls = []
    created = False
    url = "https://github.com/idleboxed/idleboxed/releases/tag/v0.1.0"

    def run(argv: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        nonlocal created
        calls.append(argv)
        stdout, stderr, status = "", "", 0

        if argv[:2] == ["git", "rev-parse"]:
            stdout = "b" * 40 if failure == "tag" and "--verify" in argv else "a" * 40

        elif argv[:3] == ["git", "remote", "get-url"]:
            stdout = "https://github.com/idleboxed/idleboxed.git"

        elif argv[:3] == ["gh", "repo", "view"]:
            assert argv[3] == "https://github.com/idleboxed/idleboxed.git"
            stdout = "idleboxed/idleboxed"

        elif argv[:2] == ["gh", "api"]:

            if created or failure == "existing":
                assets = [{"name": name, "size": (output / name).stat().st_size} for name in names]
                assets = assets[:-1] if failure == "incomplete" else assets
                stdout = json.dumps({"draft": True, "assets": assets, "html_url": url})

            else:
                status, stderr = 1, "HTTP 404"

        elif argv[:3] == ["gh", "release", "create"]:
            created = True

            if failure == "upload":
                raise BundleError("Synthetic upload failure; draft may exist")

        elif argv[:2] == ["git", "status"] or argv[:2] == ["git", "push"] or argv[:3] in (
            ["gh", "release", "edit"],
        ):
            pass

        else:
            raise AssertionError(f"Unexpected command: {argv}")

        return subprocess.CompletedProcess(argv, status, stdout, stderr)

    monkeypatch.setattr(publish, "run", run)

    if failure:

        with pytest.raises(BundleError, match="Release exists|upload failure|incomplete|Tag points"):
            publish.publish_bundle(tmp_path, config)

        assert not any(argv[:3] == ["gh", "release", "edit"] for argv in calls)

    else:
        assert publish.publish_bundle(tmp_path, config) == url
        creation = next(argv for argv in calls if argv[:3] == ["gh", "release", "create"])
        assert "--draft" in creation
        assert ("--prerelease" in creation) is (mode == "latest")
        assert all(f"{output / name}" in creation for name in names)
        assert calls[-1][-1] == "--draft=false"

    assert not any("--clobber" in argv or "--force" in argv for argv in calls)
