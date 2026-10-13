"""Synthetic data only; external commands are replaced in each test."""

import socket
from pathlib import Path
from typing import Any, NoReturn

import pytest

from iboxed.config import read_config


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("Tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "getaddrinfo", reject)


@pytest.fixture
def config(tmp_path: Path) -> dict[str, Any]:
    content = (
        'version = "0.1.0"\njobs = 2\n'
        '[paths]\nwork = "work"\noutput = "out"\ndownloads = "in/downloads"\nsdk = "in/sdk/rk3032"\n'
        '[[platforms]]\nname = "rk3032"\nvariants = ["standard", "diag"]\n'
        '[[platforms]]\nname = "linux-x86_64"\nvariants = ["standard"]\n'
    )
    (tmp_path / "config.toml").write_text(content)
    (tmp_path / "THIRD_PARTY.txt").write_text("Synthetic short licence reference\n")
    return read_config(tmp_path)
