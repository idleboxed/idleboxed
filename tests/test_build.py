import json
import logging
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any, NoReturn

import pytest

from iboxed import build
from iboxed.config import BundleError


@pytest.fixture
def commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state = {
        "calls": [], "failure": None, "builds": 0, "dirty": False,
        "unavailable_source": None, "conflicting_output": None,
        "cleanup_failures": {},
    }

    def run(argv: list[str], *, cwd: Path, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        state["calls"].append(argv)
        stdout = ""

        if argv[:2] == ["git", "status"]:
            stdout = " M config.toml\n" if state["dirty"] else ""

        elif argv[:2] == ["git", "fetch"]:
            pass

        elif argv[:2] == ["git", "rev-parse"]:

            if cwd.name == state["unavailable_source"]:
                raise BundleError("Synthetic source unavailable")

            stdout = "b" * 40 if argv[-1] == "FETCH_HEAD" else "a" * 40

        elif argv[:3] == ["git", "worktree", "add"]:
            checkout = Path(argv[-2])
            checkout.mkdir()
            python = checkout.name == "iroll"
            (checkout / ("pyproject.toml" if python else "Cargo.toml")).write_text(
                f"[{"project" if python else "package"}]\nversion = \"0.1.0\"\n"
            )
            (checkout / "Cargo.lock").write_text(
                "[[package]]\nname = \"imanlib\"\nversion = \"0.1.0\"\n"
                f"source = \"git+https://github.com/idleboxed/imanlib.git#{"c" * 40}\"\n"
            )

        elif argv[:3] == ["git", "worktree", "remove"]:

            if failure := state["cleanup_failures"].get(Path(argv[-1]).name):
                raise failure

            shutil.rmtree(argv[-1])

        elif "rollout" in argv:
            state["builds"] += 1

            if state["builds"] == 2 and state["failure"] is not None:
                raise state["failure"]

            destination = Path(argv[argv.index("--dest") + 1])
            (destination / "system/iman").mkdir(parents=True)
            platform = argv[argv.index("--platform") + 1]
            variant = "standard" if "--no-diag" in argv else "diag"
            binary = f"Synthetic {platform}/{variant} binary, not executable".encode()
            (destination / "system/iman/iman").write_bytes(binary)
            (destination / "INSTRUCTIONS.md").write_text("Synthetic guide\n")

            for directory in ("games/states", "games/saves"):
                (destination / directory).mkdir(parents=True)

            records = {"iman": {
                "source": {"kind": "local-cargo-locked"}, "files": {"iman/iman": "internal-hash"},
            }}

            (cwd / "result.json").write_text(json.dumps({"components": records}))
            stdout = json.dumps({"reports": f"{cwd}"})

            if state["builds"] == 3 and state["conflicting_output"] is not None:
                output = state["conflicting_output"]
                output.mkdir()
                (output / "marker.txt").write_text("Other build\n")

        else:
            raise AssertionError(f"Unexpected command: {argv}")

        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(build, "run", run)
    return state


@pytest.fixture
def previous_bundle(tmp_path: Path) -> Path:
    output = tmp_path / "out/0.1.0"
    (output / "system").mkdir(parents=True)
    (output / "itrampoline_libretro.so").write_bytes(b"Synthetic old trampoline core")
    (output / "system/itrampoline").write_bytes(b"Synthetic old helper")
    (output / "obsolete.txt").write_text("Old extra asset\n")
    (output / "THIRD_PARTY.txt").write_text("Old release notice\n")
    (output / "release.json").write_text("{\"version\": \"0.1.0\", \"old\": true}\n")
    return output


@pytest.mark.parametrize("latest", [False, True])
def test_matrix_uses_frozen_commits_without_building_trampoline(
    tmp_path: Path, config: dict[str, Any], commands: dict[str, Any], latest: bool,
) -> None:
    output = build.build_bundle(tmp_path, config, latest=latest)
    manifest = json.loads((output / "release.json").read_text())
    rollouts = [argv for argv in commands["calls"] if "rollout" in argv]
    assert len(rollouts) == 3
    assert all("--with-itrampoline" not in argv for argv in rollouts)
    assert ["--no-diag" in argv for argv in rollouts] == [True, False, True]
    assert set(manifest["sources"]) == {"iroll", "iman", "igui", "imanlib"}
    assert {source["commit"] for source in manifest["sources"].values()} == {"b" * 40 if latest else "a" * 40}
    assert "c" * 40 in manifest["sources"]["iman"]["imanlib"][0]["source"]
    assert "internal-hash" not in (output / "release.json").read_text()
    assert "sha256" not in (output / "release.json").read_text()
    assert sorted(path.name for path in output.iterdir()) == manifest["assets"]
    assert manifest["assets"] == sorted([
        "release.json",
        "iboxed-0.1.0-rk3032-standard.tar.gz", "iboxed-0.1.0-rk3032-diag.tar.gz",
        "iboxed-0.1.0-linux-x86_64-standard.tar.gz",
    ])
    assert all(flag not in argv for argv in rollouts for flag in ("--sdk", "--downloads", "--build-dir", "--jobs"))
    assert not Path(rollouts[0][rollouts[0].index("--source") + 1]).exists()
    fetches = [index for index, argv in enumerate(commands["calls"]) if argv[:2] == ["git", "fetch"]]
    checkouts = [index for index, argv in enumerate(commands["calls"]) if argv[:3] == ["git", "worktree", "add"]]
    assert len(fetches) == (4 if latest else 0)
    assert all(fetch < checkout for fetch in fetches for checkout in checkouts)

    for target in manifest["builds"]:

        with tarfile.open(output / target["archive"]) as archive:
            names = archive.getnames()
            assert len(names) == len(set(names))
            assert "THIRD_PARTY.txt" not in names
            assert "release.json" not in names
            assert archive.extractfile("system/release.json").read() == (output / "release.json").read_bytes()
            assert archive.extractfile("system/THIRD_PARTY.txt").read() == (tmp_path / "THIRD_PARTY.txt").read_bytes()
            expected_binary = f"Synthetic {target["platform"]}/{target["variant"]} binary, not executable".encode()
            assert archive.extractfile("system/iman/iman").read() == expected_binary
            assert "games/states" in names
            assert "system/itrampoline" not in names
            assert not any(name.startswith("system/bios") or name == "prefs.json" for name in names)


@pytest.mark.parametrize("failure", [BundleError("Synthetic failure"), KeyboardInterrupt()])
def test_failed_rebuild_cleans_worktrees_and_does_not_expose_the_previous_bundle(
    tmp_path: Path, config: dict[str, Any], commands: dict[str, Any], previous_bundle: Path, failure: BaseException,
) -> None:
    commands["failure"] = failure

    with pytest.raises(type(failure), match="Synthetic failure" if isinstance(failure, BundleError) else "^$"):
        build.build_bundle(tmp_path, config)

    assert not previous_bundle.exists()
    checkout = next(Path(argv[-2]) for argv in commands["calls"] if argv[:3] == ["git", "worktree", "add"])
    assert not checkout.parent.exists()
    assert len([argv for argv in commands["calls"] if argv[:3] == ["git", "worktree", "remove"]]) == 4


@pytest.mark.parametrize("failure", [
    pytest.param(None, id="cleanup-only"),
    pytest.param(BundleError("Synthetic build failure"), id="build-error"),
    pytest.param(KeyboardInterrupt("Synthetic cancellation"), id="cancelled"),
])
def test_cleanup_attempts_all_worktrees_and_preserves_the_primary_error(
    tmp_path: Path, commands: dict[str, Any], caplog: pytest.LogCaptureFixture, failure: BaseException | None,
) -> None:
    removal_error = BundleError("Synthetic removal failure")
    commands["cleanup_failures"] = {"imanlib": removal_error, "iman": BundleError("Other removal failure")}
    expected = failure or removal_error

    message = f"{expected}"

    with caplog.at_level(logging.ERROR, logger="iboxed.build"), pytest.raises(type(expected), match=message) as raised:

        with build.freeze_sources(tmp_path, tmp_path, latest=False):

            if failure is not None:
                raise failure

    assert raised.value is expected
    removed = [Path(argv[-1]).name for argv in commands["calls"] if argv[:3] == ["git", "worktree", "remove"]]
    assert removed == list(reversed(build.COMPONENTS))
    assert "Synthetic removal failure" in caplog.text
    assert "Other removal failure" in caplog.text
    assert not (tmp_path / "igui").exists()
    assert not (tmp_path / "iroll").exists()
    assert "Other removal failure" in "\n".join(raised.value.__notes__)


def test_cancellation_during_cleanup_still_attempts_remaining_worktrees(
    tmp_path: Path, commands: dict[str, Any],
) -> None:
    cancelled = KeyboardInterrupt()
    commands["cleanup_failures"] = {"imanlib": cancelled}

    with pytest.raises(KeyboardInterrupt) as raised:

        with build.freeze_sources(tmp_path, tmp_path, latest=False):
            pass

    assert raised.value is cancelled
    removed = [Path(argv[-1]).name for argv in commands["calls"] if argv[:3] == ["git", "worktree", "remove"]]
    assert removed == list(reversed(build.COMPONENTS))


@pytest.mark.parametrize("failure", [OSError("Synthetic packaging failure"), KeyboardInterrupt()])
def test_failed_packaging_does_not_expose_a_bundle(
    tmp_path: Path, config: dict[str, Any], commands: dict[str, Any], previous_bundle: Path,
    monkeypatch: pytest.MonkeyPatch, failure: BaseException,
) -> None:
    def reject_archive(*args: Any, **kwargs: Any) -> NoReturn:
        raise failure

    monkeypatch.setattr(build.tarfile, "open", reject_archive)
    message = "Synthetic packaging failure" if isinstance(failure, OSError) else "^$"

    with pytest.raises(type(failure), match=message):
        build.build_bundle(tmp_path, config)

    assert not previous_bundle.exists()
    assert commands["builds"] == 3
    checkout = next(Path(argv[-2]) for argv in commands["calls"] if argv[:3] == ["git", "worktree", "add"])
    assert not checkout.parent.exists()
    assert len([argv for argv in commands["calls"] if argv[:3] == ["git", "worktree", "remove"]]) == 4


def test_rebuild_removes_all_previous_assets_and_preserves_other_versions(
    tmp_path: Path, config: dict[str, Any], commands: dict[str, Any], previous_bundle: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    other_version = tmp_path / "out/0.0.9"
    other_version.mkdir()
    (other_version / "keep.txt").write_text("Keep this version\n")
    (previous_bundle / "other-version").symlink_to(other_version, target_is_directory=True)

    with caplog.at_level(logging.INFO, logger="iboxed.build"):
        output = build.build_bundle(tmp_path, config)

    manifest = json.loads((output / "release.json").read_text())
    assert output == previous_bundle
    assert sorted(path.name for path in output.iterdir()) == manifest["assets"]
    assert len(manifest["assets"]) == 4
    assert not (output / "itrampoline_libretro.so").exists()
    assert not (output / "system").exists()
    assert not (output / "obsolete.txt").exists()
    assert (other_version / "keep.txt").read_text() == "Keep this version\n"
    assert f"Removing previous bundle: {output}" in caplog.text
    assert commands["builds"] == 3


def test_dirty_sources_are_rejected_before_removing_the_previous_bundle(
    tmp_path: Path, config: dict[str, Any], commands: dict[str, Any], previous_bundle: Path,
) -> None:
    commands["dirty"] = True

    with pytest.raises(BundleError, match="Commit source and config changes"):
        build.build_bundle(tmp_path, config)

    assert (previous_bundle / "obsolete.txt").read_text() == "Old extra asset\n"
    assert commands["builds"] == 0


@pytest.mark.parametrize("source", ["", "iman"])
def test_unavailable_sources_are_rejected_before_removing_the_previous_bundle(
    tmp_path: Path, config: dict[str, Any], commands: dict[str, Any], previous_bundle: Path, source: str,
) -> None:
    commands["unavailable_source"] = (tmp_path / source).name

    with pytest.raises(BundleError, match="Synthetic source unavailable"):
        build.build_bundle(tmp_path, config)

    assert (previous_bundle / "obsolete.txt").read_text() == "Old extra asset\n"
    assert commands["builds"] == 0


@pytest.mark.parametrize("version", [
    "", ".", "..", "../0.1.0", "out/0.1.0", "0.1.0/", "/tmp/iboxed-unsafe", "..\\0.1.0", "0.1.0\x00", 0, None,
])
def test_unsafe_version_is_rejected_without_removing_any_output(
    tmp_path: Path, config: dict[str, Any], commands: dict[str, Any], previous_bundle: Path, version: object,
) -> None:
    config["version"] = version

    with pytest.raises(BundleError, match="single directory name"):
        build.build_bundle(tmp_path, config)

    assert (previous_bundle / "obsolete.txt").read_text() == "Old extra asset\n"
    assert not commands["calls"]


@pytest.mark.parametrize("location", ["out", "out/0.1.0"])
@pytest.mark.parametrize("target", ["outside", "missing"])
def test_symlink_output_is_rejected_without_touching_its_target(
    tmp_path: Path, config: dict[str, Any], commands: dict[str, Any], location: str, target: str,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("Keep outside data\n")
    link = tmp_path / location
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(tmp_path / target, target_is_directory=True)

    with pytest.raises(BundleError, match="not a symlink"):
        build.build_bundle(tmp_path, config)

    assert link.is_symlink()
    assert (outside / "keep.txt").read_text() == "Keep outside data\n"
    assert not commands["calls"]


@pytest.mark.parametrize("location", ["out", "out/0.1.0"])
def test_file_output_is_rejected_without_removing_it(
    tmp_path: Path, config: dict[str, Any], commands: dict[str, Any], location: str,
) -> None:
    output = tmp_path / location
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("Unrelated file\n")

    with pytest.raises(BundleError, match="must be a directory"):
        build.build_bundle(tmp_path, config)

    assert output.read_text() == "Unrelated file\n"
    assert not commands["calls"]


def test_output_created_during_build_is_not_mixed_with_the_new_bundle(
    tmp_path: Path, config: dict[str, Any], commands: dict[str, Any],
) -> None:
    output = tmp_path / "out/0.1.0"
    commands["conflicting_output"] = output

    with pytest.raises(BundleError, match="output appeared during the build"):
        build.build_bundle(tmp_path, config)

    assert [path.name for path in output.iterdir()] == ["marker.txt"]
    assert (output / "marker.txt").read_text() == "Other build\n"
    checkout = next(Path(argv[-2]) for argv in commands["calls"] if argv[:3] == ["git", "worktree", "add"])
    assert not checkout.parent.exists()
