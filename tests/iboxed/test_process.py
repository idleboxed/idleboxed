import signal
from pathlib import Path

import pytest

from iboxed import process
from iboxed.config import BundleError


@pytest.mark.parametrize("scenario", ["success", "failure", "cancel"])
def test_external_command_errors_and_cancellation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str) -> None:
    signals = []

    class Child:
        pid = 42
        returncode = 1 if scenario == "failure" else 0

        def __enter__(self) -> "Child":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def communicate(self, *, timeout: int | None = None) -> tuple[str, str]:

            if scenario == "cancel" and timeout is None:
                raise KeyboardInterrupt

            return "Synthetic stdout", "Synthetic error"

    monkeypatch.setattr(process.subprocess, "Popen", lambda *args, **kwargs: Child())
    monkeypatch.setattr(process.os, "killpg", lambda pid, value: signals.append((pid, value)))

    if scenario == "cancel":

        with pytest.raises(KeyboardInterrupt):
            process.run(["synthetic"], cwd=tmp_path)

        assert signals == [(42, signal.SIGINT)]

    elif scenario == "failure":

        with pytest.raises(BundleError, match="Synthetic error"):
            process.run(["synthetic"], cwd=tmp_path)

    else:
        assert process.run(["synthetic"], cwd=tmp_path).stdout == "Synthetic stdout"
