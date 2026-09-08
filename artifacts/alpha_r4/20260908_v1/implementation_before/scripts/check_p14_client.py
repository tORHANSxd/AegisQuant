"""Regenerate the P14 TypeScript client in isolation and reject drift."""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
import tempfile
from pathlib import Path


def _inventory(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*.ts"))
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise SystemExit("required command is unavailable: pnpm")
    runtime = root / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="p14-client-", dir=runtime) as temporary:
        generated = Path(temporary) / "client"
        web = root / "apps/web"
        config = web / f".p14-client-{Path(temporary).name}.config.ts"
        config.write_text(
            'import { defineConfig } from "@hey-api/openapi-ts";\n\n'
            "export default defineConfig({\n"
            '  input: "./src/generated/openapi.json",\n'
            f"  output: {json.dumps(generated.as_posix())},\n"
            "});\n",
            encoding="utf-8",
            newline="\n",
        )
        try:
            result = subprocess.run(  # noqa: S603  # nosec B603
                [
                    pnpm,
                    "exec",
                    "openapi-ts",
                    "--file",
                    str(config),
                    "--no-log-file",
                    "--silent",
                ],
                cwd=web,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        finally:
            config.unlink(missing_ok=True)
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            return result.returncode
        expected = _inventory(root / "apps/web/src/generated/client")
        actual = _inventory(generated)
    if expected != actual:
        missing = sorted(expected.keys() - actual.keys())
        unexpected = sorted(actual.keys() - expected.keys())
        changed = sorted(
            path for path in expected.keys() & actual.keys() if expected[path] != actual[path]
        )
        print(
            f"P14 generated client drift: missing={missing}, unexpected={unexpected}, changed={changed}"
        )
        return 1
    print(f"verified {len(expected)} generated TypeScript client files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
