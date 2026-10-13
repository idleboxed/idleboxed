from pathlib import Path
from typing import Any

import pytest

from iboxed import cli
from iboxed.config import BundleError, read_config


@pytest.mark.parametrize("arguments,expected", [
    (["build"], False), (["build", "--latest"], True), (["publish"], "publish"),
])
def test_approved_commands_are_separate(
    tmp_path: Path, config: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
    arguments: list[str], expected: bool | str,
) -> None:
    calls = []

    def build(root: Path, config: dict[str, Any], *, latest: bool) -> Path:
        calls.append(latest)
        return root / "out"

    def publish(root: Path, config: dict[str, Any]) -> str:
        calls.append("publish")
        return "https://example.invalid/release"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "build_bundle", build)
    monkeypatch.setattr(cli, "publish_bundle", publish)

    assert cli.main(arguments) == 0
    assert calls == [expected]


@pytest.mark.parametrize("old,new", [
    ('version = "0.1.0"', 'version = "../escape"'),
    ('name = "linux-x86_64"\nvariants = ["standard"]', 'name = "linux-x86_64"\nvariants = ["diag"]'),
    ('variants = ["standard", "diag"]', 'variants = ["standard", "standard"]'),
])
def test_invalid_config_fails_before_building(tmp_path: Path, config: dict[str, Any], old: str, new: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(path.read_text().replace(old, new))

    with pytest.raises(BundleError, match="version|Supported targets|duplicate targets"):
        read_config(tmp_path)

    assert not (tmp_path / "work").exists()


def test_cancellation_returns_130(
    tmp_path: Path, config: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    def cancel(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "build_bundle", cancel)

    assert cli.main(["build"]) == 130
