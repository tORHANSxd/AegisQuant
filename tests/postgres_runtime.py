"""Disposable loopback-only PostgreSQL process for contract tests."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess  # nosec B404
import tempfile
from dataclasses import dataclass
from pathlib import Path


def available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@dataclass(slots=True)
class PostgresTestServer:
    root: Path
    bin_dir: Path
    data_dir: Path | None = None
    port: int | None = None

    @property
    def dsn(self) -> str:
        if self.port is None:
            raise RuntimeError("PostgreSQL test server is not running")
        return f"postgresql+psycopg://postgres@127.0.0.1:{self.port}/postgres"

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["PATH"] = f"{self.bin_dir}{os.pathsep}{environment.get('PATH', '')}"
        return environment

    def _run(
        self,
        executable: str,
        arguments: list[str],
        *,
        timeout: int = 60,
        capture_output: bool = True,
    ) -> None:
        command = [str(self.bin_dir / executable), *arguments]
        result = subprocess.run(  # nosec B603 - pinned local executable
            command,
            cwd=self.root,
            check=False,
            stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture_output else subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=self._environment(),
        )
        if result.returncode != 0:
            output = "\n".join(part for part in (result.stdout, result.stderr) if part)
            raise RuntimeError(f"PostgreSQL command failed: {executable}\n{output}")

    def start(self) -> None:
        if self.data_dir is not None:
            raise RuntimeError("PostgreSQL test server is already started")
        runtime_root = (self.root / ".runtime/postgres-tests").resolve()
        runtime_root.mkdir(parents=True, exist_ok=True)
        self.data_dir = Path(tempfile.mkdtemp(prefix="cluster-", dir=runtime_root)).resolve()
        self.port = available_port()
        self._run(
            "initdb.exe",
            [
                "-D",
                str(self.data_dir),
                "--username=postgres",
                "--auth-host=trust",
                "--auth-local=trust",
                "--encoding=UTF8",
                "--locale=C",
                "--no-sync",
            ],
        )
        log_path = self.data_dir / "postgres.log"
        options = f"-p {self.port} -h 127.0.0.1 -c max_connections=20"
        self._run(
            "pg_ctl.exe",
            [
                "-D",
                str(self.data_dir),
                "-l",
                str(log_path),
                "-w",
                "-t",
                "60",
                "-o",
                options,
                "start",
            ],
            timeout=75,
            capture_output=False,
        )

    def stop(self) -> None:
        data_dir = self.data_dir
        if data_dir is None:
            return
        try:
            if (data_dir / "PG_VERSION").is_file():
                self._run(
                    "pg_ctl.exe",
                    ["-D", str(data_dir), "-w", "-t", "60", "-m", "fast", "stop"],
                    timeout=75,
                )
        finally:
            runtime_root = (self.root / ".runtime/postgres-tests").resolve()
            if runtime_root not in data_dir.parents:
                raise RuntimeError("refusing to remove PostgreSQL data outside test runtime")
            shutil.rmtree(data_dir, ignore_errors=True)
            self.data_dir = None
            self.port = None
