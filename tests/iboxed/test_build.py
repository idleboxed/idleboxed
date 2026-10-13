import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest

from iboxed import build
from iboxed.config import BundleError


@pytest.fixture
def commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state = {"calls": [], "failure": None, "builds": 0}

    def run(argv: list[str], *, cwd: Path, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        state["calls"].append(argv)
        stdout = ""

        if argv[:2] == ["git", "status"]:
            pass

        elif argv[:2] == ["git", "fetch"]:
            pass

        elif argv[:2] == ["git", "rev-parse"]:
            stdout = "b" * 40 if argv[-1] == "FETCH_HEAD" else "a" * 40

        elif argv[:3] == ["git", "worktree", "add"]:
            checkout = Path(argv[-2])
            checkout.mkdir()
            python = checkout.name in ("iroll", "itrampoline")
            (checkout / ("pyproject.toml" if python else "Cargo.toml")).write_text(
                f'[{"project" if python else "package"}]\nversion = "0.1.0"\n'
            )
            (checkout / "Cargo.lock").write_text(
                '[[package]]\nname = "imanlib"\nversion = "0.1.0"\n'
                f'source = "git+https://github.com/idleboxed/imanlib.git#{"c" * 40}"\n'
            )

        elif argv[:3] == ["git", "worktree", "remove"]:
            shutil.rmtree(argv[-1])

        elif "rollout" in argv:
            state["builds"] += 1

            if state["builds"] == 2 and state["failure"] is not None:
                raise state["failure"]

            destination = Path(argv[argv.index("--dest") + 1])
            (destination / "system/iman").mkdir(parents=True)
            (destination / "system/iman/iman").write_bytes(b"Synthetic binary, not executable")
            (destination / "INSTRUCTIONS.md").write_text("Synthetic guide\n")

            for directory in ("games/states", "games/saves"):
                (destination / directory).mkdir(parents=True)

            records = {"iman": {
                "source": {"kind": "local-cargo-locked"}, "files": {"iman/iman": "internal-hash"},
            }}

            if "--with-itrampoline" in argv:
                (destination / "system/itrampoline").write_bytes(b"Synthetic helper")
                (destination / "system/itrampoline").chmod(0o755)
                core = cwd / "synthetic.so"
                core.write_bytes(b"Synthetic core")
                records["itrampoline"] = {
                    "source": {"kind": "local-python-runtime"}, "files": {"itrampoline": "internal-hash"},
                    "artifacts": {"core": {"path": f"{core}"}},
                }

            (cwd / "result.json").write_text(json.dumps({"components": records}))
            stdout = json.dumps({"reports": f"{cwd}"})

        else:
            raise AssertionError(f"Unexpected command: {argv}")

        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(build, "run", run)
    return state


@pytest.mark.parametrize("latest", [False, True])
def test_matrix_uses_frozen_commits_and_builds_trampoline_once(
    tmp_path: Path, config: dict[str, Any], commands: dict[str, Any], latest: bool,
) -> None:
    output = build.build_bundle(tmp_path, config, latest=latest)
    manifest = json.loads((output / "release.json").read_text())
    rollouts = [argv for argv in commands["calls"] if "rollout" in argv]
    assert len(rollouts) == 3
    assert ["--with-itrampoline" in argv for argv in rollouts] == [True, False, False]
    assert ["--no-diag" in argv for argv in rollouts] == [True, False, True]
    assert {source["commit"] for source in manifest["sources"].values()} == {"b" * 40 if latest else "a" * 40}
    assert "c" * 40 in manifest["sources"]["iman"]["imanlib"][0]["source"]
    assert "internal-hash" not in (output / "release.json").read_text()
    assert "sha256" not in (output / "release.json").read_text()
    assert sorted(path.name for path in output.iterdir()) == manifest["assets"]
    assert not list((tmp_path / "work").glob("bundle-*"))
    fetches = [index for index, argv in enumerate(commands["calls"]) if argv[:2] == ["git", "fetch"]]
    checkouts = [index for index, argv in enumerate(commands["calls"]) if argv[:3] == ["git", "worktree", "add"]]
    assert len(fetches) == (5 if latest else 0)
    assert all(fetch < checkout for fetch in fetches for checkout in checkouts)

    for target in manifest["builds"]:

        with tarfile.open(output / target["archive"]) as archive:
            names = archive.getnames()
            assert "THIRD_PARTY.txt" in names
            assert "games/states" in names
            assert ("system/itrampoline" in names) is (target["platform"] == "rk3032")
            assert not any(name.startswith("system/bios") or name == "prefs.json" for name in names)


@pytest.mark.parametrize("failure", [BundleError("Synthetic failure"), KeyboardInterrupt()])
def test_partial_matrix_failure_cleans_worktrees_and_does_not_expose_a_bundle(
    tmp_path: Path, config: dict[str, Any], commands: dict[str, Any], failure: BaseException,
) -> None:
    commands["failure"] = failure

    with pytest.raises(type(failure), match="Synthetic failure" if isinstance(failure, BundleError) else "^$"):
        build.build_bundle(tmp_path, config)

    assert not (tmp_path / "out/0.1.0").exists()
    assert not list((tmp_path / "work").glob("bundle-*"))
    assert len([argv for argv in commands["calls"] if argv[:3] == ["git", "worktree", "remove"]]) == 5


def test_existing_bundle_is_not_replaced(tmp_path: Path, config: dict[str, Any], commands: dict[str, Any]) -> None:
    (tmp_path / "out/0.1.0").mkdir(parents=True)

    with pytest.raises(BundleError, match="already exists"):
        build.build_bundle(tmp_path, config)

    assert not commands["calls"]
