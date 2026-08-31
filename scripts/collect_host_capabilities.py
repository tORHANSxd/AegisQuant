"""Collect local host capabilities without network or credential access."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import shutil
import subprocess  # nosec B404
import sys
import winreg
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

COMMAND_TIMEOUT_SECONDS: Final = 15


class MemoryStatusEx(ctypes.Structure):
    """Windows MEMORYSTATUSEX structure."""

    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def decode_output(raw: bytes) -> str:
    """Decode ordinary UTF-8 and the UTF-16LE output emitted by some WSL builds."""
    if not raw:
        return ""
    encoding = "utf-16-le" if raw.count(b"\x00") > len(raw) // 8 else "utf-8"
    return raw.decode(encoding, errors="replace").strip().lstrip("\ufeff")


def local_command(executable: str, *arguments: str) -> dict[str, object]:
    """Return bounded output from a fixed local capability command."""
    resolved = shutil.which(executable)
    if resolved is None:
        return {"available": False, "exit_code": None, "output": ""}
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        # The executable is resolved before use and no shell is used.
        result = subprocess.run(  # noqa: S603  # nosec B603
            [resolved, *arguments],
            check=False,
            capture_output=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            creationflags=creation_flags,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "available": True,
            "exit_code": None,
            "output": "",
            "error_type": type(exc).__name__,
        }
    output = decode_output(result.stdout or result.stderr)
    return {
        "available": True,
        "exit_code": result.returncode,
        "output": output[:2000],
    }


def total_memory_bytes() -> int | None:
    """Read physical memory on Windows without a third-party dependency."""
    if os.name != "nt":
        return None
    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.ullTotalPhys)


def processor_name() -> str:
    """Read the Windows processor name, falling back to platform metadata."""
    if os.name == "nt":
        key_path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"  # pragma: allowlist secret
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                if isinstance(value, str):
                    return value.strip()
        except OSError:
            pass
    return platform.processor() or "unknown"


def collect(workspace: Path) -> dict[str, object]:
    """Collect only capability facts relevant to the taskbook."""
    usage = shutil.disk_usage(workspace.resolve())
    return {
        "schema_version": "1.0.0",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "collector": "scripts/collect_host_capabilities.py",
        "network_access_performed": False,
        "secrets_read": False,
        "operating_system": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "cpu": {"logical_count": os.cpu_count(), "name": processor_name()},
        "memory": {"total_bytes": total_memory_bytes()},
        "workspace_disk": {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
        },
        "runtimes": {
            "python": {
                "version": platform.python_version(),
                "implementation": platform.python_implementation(),
                "executable_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
            },
            "node": local_command("node", "--version"),
            "pnpm": local_command("pnpm", "--version"),
            "uv": local_command("uv", "--version"),
        },
        "platform_tools": {
            "wsl": local_command("wsl.exe", "--version"),
            "docker": local_command("docker", "--version"),
            "nvidia_smi": local_command(
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader",
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("state/HOST_CAPABILITIES.json"))
    args = parser.parse_args()
    payload = collect(args.workspace)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote host capabilities to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
