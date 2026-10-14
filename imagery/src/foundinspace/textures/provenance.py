from __future__ import annotations

import hashlib
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

from .util import sha256_file

_DISTRIBUTION = "found-in-space-pas-de-geant-texture-pipeline"


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _code_tree_sha256(repository: Path) -> str:
    files = sorted((repository / "src").rglob("*.py"))
    files.extend(
        path
        for path in (repository / "pyproject.toml", repository / "uv.lock")
        if path.is_file()
    )
    digest = hashlib.sha256()
    for path in sorted(files):
        relative = path.relative_to(repository).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def producer_identity() -> dict[str, Any]:
    repository = _repository_root()
    try:
        package_version = metadata.version(_DISTRIBUTION)
    except metadata.PackageNotFoundError:
        package_version = None
    identity: dict[str, Any] = {
        "package_version": package_version,
        "code_tree_sha256": _code_tree_sha256(repository),
    }
    try:
        sha = subprocess.run(
            ("git", "-C", str(repository), "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            (
                "git",
                "-C",
                str(repository),
                "status",
                "--porcelain",
                "--untracked-files=all",
            ),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        identity.update({"git_sha": None, "git_dirty": None})
    else:
        identity.update({"git_sha": sha, "git_dirty": bool(status.strip())})
    return identity
