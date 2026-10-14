"""External commands; let iroll clean up its compilers on cancellation."""

import os
import signal
import subprocess
from pathlib import Path

from .config import BundleError


def run(argv: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a command, capture its output and stop its process group on cancellation."""

    with subprocess.Popen(
        argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    ) as child:
        try:
            stdout, stderr = child.communicate()

        except KeyboardInterrupt:
            try:
                os.killpg(child.pid, signal.SIGINT)

            except ProcessLookupError:
                pass
            try:
                child.communicate(timeout=5)

            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()

            raise

    if check and child.returncode:
        raise BundleError(f"{argv[0]} failed:\n{stderr[-2000:]}")

    return subprocess.CompletedProcess(argv, child.returncode, stdout, stderr)
