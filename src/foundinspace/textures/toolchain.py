from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ToolError(RuntimeError):
    """Raised when an external raster tool fails or returns invalid data."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    argv: tuple[str, ...]
    stdout: str
    stderr: str


def require_tools(names: Sequence[str]) -> dict[str, str]:
    paths: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        path = shutil.which(name)
        if path is None:
            missing.append(name)
        else:
            paths[name] = path
    if missing:
        raise ToolError(f"required external tool(s) not found: {', '.join(missing)}")
    return paths


def run_command(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> CommandResult:
    command = [str(item) for item in argv]
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            env=process_env,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ToolError(f"external tool not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise ToolError(f"command failed ({' '.join(command)}): {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"command timed out: {' '.join(command)}") from exc
    return CommandResult(tuple(command), completed.stdout, completed.stderr)


def tool_versions() -> dict[str, str]:
    require_tools(("gdalinfo", "gdalwarp", "gdal_translate", "proj"))
    return {
        "gdal": run_command(("gdalinfo", "--version"), timeout=10).stdout.strip(),
        "proj": run_command(("proj",), timeout=10).stderr.strip().splitlines()[0],
    }


def gdalinfo(path: Path) -> tuple[dict[str, Any], CommandResult]:
    result = run_command(("gdalinfo", "-json", str(path)))
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ToolError(f"gdalinfo returned invalid JSON for {path}") from exc
    if not isinstance(payload, dict):
        raise ToolError(f"gdalinfo returned a non-object for {path}")
    return payload, result


def spatial_reference_proj4(path: Path) -> tuple[str, CommandResult]:
    result = run_command(("gdalsrsinfo", "-o", "proj4", str(path)))
    value = result.stdout.strip()
    if not value:
        raise ToolError(f"gdalsrsinfo returned an empty spatial reference for {path}")
    return value, result
