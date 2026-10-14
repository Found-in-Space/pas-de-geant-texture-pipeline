from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .project import AcquisitionSpec
from .provenance import producer_identity
from .util import atomic_write_json, sha256_file, utc_now

USER_AGENT = "found-in-space-pas-de-geant-textures/0.1"
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024
STATE_INTERVAL_BYTES = 64 * 1024 * 1024
DEFAULT_MINIMUM_FREE_BYTES = 5_000_000_000


class AcquisitionError(RuntimeError):
    """Raised when a source cannot be downloaded or authenticated."""


OpenUrl = Callable[..., BinaryIO]


def _response_status(response: Any) -> int:
    status = getattr(response, "status", None)
    if status is None:
        status = response.getcode()
    return int(status)


def _selected_headers(response: Any) -> dict[str, str]:
    headers = response.headers
    selected = {}
    for name in (
        "Accept-Ranges",
        "Content-Length",
        "Content-Range",
        "Content-Type",
        "ETag",
        "Last-Modified",
    ):
        value = headers.get(name)
        if value is not None:
            selected[name.lower()] = value
    return selected


def _remote_total(headers: dict[str, str], *, offset: int) -> int | None:
    content_range = headers.get("content-range")
    if content_range and "/" in content_range:
        total = content_range.rsplit("/", 1)[1]
        if total != "*":
            return int(total)
    content_length = headers.get("content-length")
    if content_length is not None:
        return offset + int(content_length)
    return None


def _paths(spec: AcquisitionSpec, source_root: Path) -> tuple[Path, Path, Path]:
    destination = source_root / spec.filename
    partial = source_root / f".{spec.filename}.part"
    state = source_root / f".{spec.filename}.download-state.json"
    return destination, partial, state


def _resume_validator(
    spec: AcquisitionSpec, state_path: Path, *, offset: int
) -> tuple[dict[str, Any], str]:
    if not state_path.is_file():
        raise AcquisitionError(
            "partial source has no download state; refusing an unauthenticated resume"
        )
    try:
        previous = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcquisitionError(f"download state is unreadable: {state_path}") from exc
    if (
        previous.get("source_id") != spec.source_id
        or previous.get("url") != spec.url
        or previous.get("filename") != spec.filename
    ):
        raise AcquisitionError(
            "partial source download state does not match the acquisition specification"
        )
    if previous.get("partial_bytes") != offset:
        raise AcquisitionError(
            "partial source size does not match its recorded download state"
        )
    response_headers = previous.get("response_headers")
    if not isinstance(response_headers, dict):
        raise AcquisitionError("partial source download state has no response headers")
    validator = response_headers.get("etag") or response_headers.get("last-modified")
    if not isinstance(validator, str) or not validator:
        raise AcquisitionError(
            "remote source supplied no ETag or Last-Modified validator; refusing resume"
        )
    return previous, validator


def _verify_local(path: Path, spec: AcquisitionSpec) -> tuple[int, str]:
    if not path.is_file():
        raise AcquisitionError(f"source path is not a regular file: {path}")
    size = path.stat().st_size
    if spec.expected.size_bytes is not None and size != spec.expected.size_bytes:
        raise AcquisitionError(
            f"source size mismatch: expected {spec.expected.size_bytes}, got {size}"
        )
    checksum = sha256_file(path)
    if spec.expected.sha256 is not None and checksum != spec.expected.sha256:
        raise AcquisitionError(
            f"source SHA-256 mismatch: expected {spec.expected.sha256}, got {checksum}"
        )
    return size, checksum


def _receipt(
    *,
    spec: AcquisitionSpec,
    path: Path,
    size: int,
    checksum: str,
    headers: dict[str, str],
    final_url: str,
    resumed_from: int,
) -> dict[str, Any]:
    return {
        "format_version": 1,
        "source_id": spec.source_id,
        "source_status": spec.status,
        "contract_verified": spec.status == "admitted" and spec.expected.complete,
        "requested_url": spec.url,
        "final_url": final_url,
        "filename": path.name,
        "size_bytes": size,
        "sha256": checksum,
        "response_headers": headers,
        "resumed_from_bytes": resumed_from,
        "completed_at": utc_now(),
        "producer": producer_identity(),
    }


def download_source(
    spec: AcquisitionSpec,
    source_root: Path,
    *,
    timeout: float = 60.0,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    minimum_free_bytes: int = DEFAULT_MINIMUM_FREE_BYTES,
    opener: OpenUrl = urlopen,
) -> dict[str, Any]:
    """Download one source with resumable partial state and atomic promotion."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if minimum_free_bytes < 0:
        raise ValueError("minimum_free_bytes must be >= 0")
    source_root = source_root.resolve()
    if source_root == Path(source_root.anchor):
        raise AcquisitionError("refusing to use a filesystem root as source_root")
    source_root.mkdir(parents=True, exist_ok=True)
    destination, partial, state_path = _paths(spec, source_root)
    receipt_path = destination.with_name(f"{destination.name}.download.json")

    if destination.exists():
        size, checksum = _verify_local(destination, spec)
        if receipt_path.is_file():
            try:
                previous = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise AcquisitionError(
                    f"download receipt is unreadable: {receipt_path}"
                ) from exc
            if (
                previous.get("source_id") != spec.source_id
                or previous.get("size_bytes") != size
                or previous.get("sha256") != checksum
            ):
                raise AcquisitionError(
                    f"download receipt does not authenticate cached source: {receipt_path}"
                )
            receipt = {
                **previous,
                "source_status": spec.status,
                "contract_verified": spec.status == "admitted"
                and spec.expected.complete,
                "verified_at": utc_now(),
                "verified_by_producer": producer_identity(),
            }
        else:
            receipt = _receipt(
                spec=spec,
                path=destination,
                size=size,
                checksum=checksum,
                headers={},
                final_url=spec.url,
                resumed_from=size,
            )
        atomic_write_json(receipt_path, receipt)
        return receipt

    offset = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    previous_state = None
    if offset:
        previous_state, validator = _resume_validator(spec, state_path, offset=offset)
        headers["Range"] = f"bytes={offset}-"
        headers["If-Range"] = validator
    request = Request(spec.url, headers=headers)
    started_at = (
        previous_state.get("started_at")
        if previous_state and isinstance(previous_state.get("started_at"), str)
        else utc_now()
    )
    state: dict[str, Any] = {
        "format_version": 1,
        "source_id": spec.source_id,
        "url": spec.url,
        "filename": spec.filename,
        "status": "downloading",
        "started_at": started_at,
        "updated_at": started_at,
        "partial_bytes": offset,
    }
    if previous_state:
        state["response_headers"] = previous_state["response_headers"]
    atomic_write_json(state_path, state)
    try:
        response_context = opener(request, timeout=timeout)  # noqa: S310
        with response_context as response:
            status = _response_status(response)
            response_headers = _selected_headers(response)
            final_url = response.geturl() if hasattr(response, "geturl") else spec.url
            if offset and status != 206:
                raise AcquisitionError(
                    "server did not honor the resume Range request; partial file was preserved"
                )
            if not offset and status not in {200, 206}:
                raise AcquisitionError(f"unexpected HTTP status {status}")
            content_range = response_headers.get("content-range")
            if (
                offset
                and content_range
                and not content_range.startswith(f"bytes {offset}-")
            ):
                raise AcquisitionError(
                    f"resume response starts at the wrong byte: {content_range}"
                )
            remote_total = _remote_total(response_headers, offset=offset)
            if (
                remote_total is not None
                and spec.expected.size_bytes is not None
                and remote_total != spec.expected.size_bytes
            ):
                raise AcquisitionError(
                    "remote size does not match admitted source contract: "
                    f"expected {spec.expected.size_bytes}, got {remote_total}"
                )
            available_bytes = shutil.disk_usage(source_root).free
            remaining_bytes = (
                max(0, remote_total - offset) if remote_total is not None else None
            )
            if (
                remaining_bytes is not None
                and available_bytes < remaining_bytes + minimum_free_bytes
            ):
                raise AcquisitionError(
                    "insufficient source-root free space: "
                    f"need {remaining_bytes + minimum_free_bytes} bytes including "
                    f"reserve, have {available_bytes}"
                )

            state.update(
                {
                    "http_status": status,
                    "final_url": final_url,
                    "response_headers": response_headers,
                    "remote_total_bytes": remote_total,
                    "available_bytes_before_transfer": available_bytes,
                    "minimum_free_bytes": minimum_free_bytes,
                }
            )
            atomic_write_json(state_path, state)
            downloaded = offset
            next_state_at = downloaded + STATE_INTERVAL_BYTES
            with partial.open("ab") as stream:
                while True:
                    block = response.read(chunk_size)
                    if not block:
                        break
                    stream.write(block)
                    downloaded += len(block)
                    if downloaded >= next_state_at:
                        stream.flush()
                        os.fsync(stream.fileno())
                        state.update(updated_at=utc_now(), partial_bytes=downloaded)
                        atomic_write_json(state_path, state)
                        next_state_at = downloaded + STATE_INTERVAL_BYTES
                stream.flush()
                os.fsync(stream.fileno())

        actual_size = partial.stat().st_size
        if remote_total is not None and actual_size != remote_total:
            raise AcquisitionError(
                f"incomplete download: remote reports {remote_total} bytes, got {actual_size}"
            )
        checksum = sha256_file(partial)
        if (
            spec.expected.size_bytes is not None
            and actual_size != spec.expected.size_bytes
        ):
            raise AcquisitionError(
                f"source size mismatch: expected {spec.expected.size_bytes}, got {actual_size}"
            )
        if spec.expected.sha256 is not None and checksum != spec.expected.sha256:
            raise AcquisitionError(
                f"source SHA-256 mismatch: expected {spec.expected.sha256}, got {checksum}"
            )
        partial.replace(destination)
        receipt = _receipt(
            spec=spec,
            path=destination,
            size=actual_size,
            checksum=checksum,
            headers=response_headers,
            final_url=final_url,
            resumed_from=offset,
        )
        atomic_write_json(receipt_path, receipt)
        state.update(
            status="complete",
            updated_at=utc_now(),
            partial_bytes=actual_size,
            sha256=checksum,
            receipt=str(receipt_path),
        )
        atomic_write_json(state_path, state)
        return receipt
    except (HTTPError, URLError, OSError, ValueError, AcquisitionError) as exc:
        state.update(
            status="failed",
            updated_at=utc_now(),
            partial_bytes=partial.stat().st_size if partial.exists() else offset,
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        atomic_write_json(state_path, state)
        if isinstance(exc, AcquisitionError):
            raise
        raise AcquisitionError(f"could not download {spec.url}: {exc}") from exc
