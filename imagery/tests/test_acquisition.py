from __future__ import annotations

import hashlib
import io
import json
from email.message import Message
from pathlib import Path

import pytest

import foundinspace.textures.acquisition as acquisition
from foundinspace.textures.acquisition import AcquisitionError, download_source
from foundinspace.textures.project import AcquisitionSpec, ExpectedSource


class FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, *, status: int, headers: dict[str, str]):
        super().__init__(payload)
        self.status = status
        self.headers = Message()
        for name, value in headers.items():
            self.headers[name] = value

    def geturl(self) -> str:
        return "https://cdn.example.test/source.tif"


def _spec(payload: bytes, *, admitted: bool = True) -> AcquisitionSpec:
    expected = (
        ExpectedSource(
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            width=8,
            height=4,
            band_count=1,
            data_type="Byte",
            geo_transform=(-4.0, 1.0, 0.0, 2.0, 0.0, -1.0),
            nodata="absent",
            mask_flags=("ALL_VALID",),
            scale="absent",
            offset="absent",
        )
        if admitted
        else ExpectedSource()
    )
    return AcquisitionSpec(
        path=Path("source.toml"),
        status="admitted" if admitted else "candidate",
        source_id="source",
        title="Source",
        landing_page="https://example.test",
        url="https://example.test/source.tif",
        filename="source.tif",
        citation="Citation",
        source_crs=None,
        expected=expected,
        reported={},
    )


def test_download_verifies_and_atomically_promotes(tmp_path: Path) -> None:
    payload = b"complete payload"
    requests = []

    def opener(request, *, timeout):
        requests.append(request)
        return FakeResponse(
            payload,
            status=200,
            headers={"Content-Length": str(len(payload)), "ETag": '"source-v1"'},
        )

    receipt = download_source(_spec(payload), tmp_path / "sources", opener=opener)

    source = tmp_path / "sources/source.tif"
    assert source.read_bytes() == payload
    assert not (tmp_path / "sources/.source.tif.part").exists()
    assert receipt["contract_verified"] is True
    assert receipt["sha256"] == hashlib.sha256(payload).hexdigest()
    saved = json.loads((tmp_path / "sources/source.tif.download.json").read_text())
    assert saved["response_headers"]["etag"] == '"source-v1"'
    assert requests[0].get_header("Range") is None


def test_download_resumes_only_from_matching_range_response(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / ".source.tif.part").write_bytes(b"abc")
    (source_root / ".source.tif.download-state.json").write_text(
        json.dumps(
            {
                "source_id": "source",
                "url": "https://example.test/source.tif",
                "filename": "source.tif",
                "partial_bytes": 3,
                "started_at": "2026-10-02T00:00:00Z",
                "response_headers": {"etag": '"v1"'},
            }
        ),
        encoding="utf-8",
    )
    payload = b"abcdef"
    seen_headers = []

    def opener(request, *, timeout):
        seen_headers.append(
            (request.get_header("Range"), request.get_header("If-range"))
        )
        return FakeResponse(
            b"def",
            status=206,
            headers={
                "Content-Length": "3",
                "Content-Range": "bytes 3-5/6",
            },
        )

    receipt = download_source(_spec(payload), source_root, opener=opener)

    assert (source_root / "source.tif").read_bytes() == payload
    assert receipt["resumed_from_bytes"] == 3
    assert seen_headers == [("bytes=3-", '"v1"')]


def test_download_preserves_partial_when_server_ignores_range(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    partial = source_root / ".source.tif.part"
    partial.write_bytes(b"abc")
    (source_root / ".source.tif.download-state.json").write_text(
        json.dumps(
            {
                "source_id": "source",
                "url": "https://example.test/source.tif",
                "filename": "source.tif",
                "partial_bytes": 3,
                "started_at": "2026-10-02T00:00:00Z",
                "response_headers": {"last-modified": "Thu, 02 Oct 2026 00:00:00 GMT"},
            }
        ),
        encoding="utf-8",
    )

    def opener(request, *, timeout):
        return FakeResponse(b"abcdef", status=200, headers={"Content-Length": "6"})

    with pytest.raises(AcquisitionError, match="did not honor"):
        download_source(_spec(b"abcdef"), source_root, opener=opener)

    assert partial.read_bytes() == b"abc"
    state = json.loads((source_root / ".source.tif.download-state.json").read_text())
    assert state["status"] == "failed"


def test_download_refuses_resume_without_remote_validator(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / ".source.tif.part").write_bytes(b"abc")
    (source_root / ".source.tif.download-state.json").write_text(
        json.dumps(
            {
                "source_id": "source",
                "url": "https://example.test/source.tif",
                "filename": "source.tif",
                "partial_bytes": 3,
                "response_headers": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AcquisitionError, match="no ETag or Last-Modified"):
        download_source(
            _spec(b"abcdef"),
            source_root,
            opener=lambda *args, **kwargs: pytest.fail("must not contact network"),
        )


def test_download_keeps_failed_checksum_as_unpromoted_partial(tmp_path: Path) -> None:
    payload = b"unexpected"

    def opener(request, *, timeout):
        return FakeResponse(
            payload, status=200, headers={"Content-Length": str(len(payload))}
        )

    with pytest.raises(AcquisitionError, match="SHA-256 mismatch"):
        download_source(_spec(b"same-size!"), tmp_path / "sources", opener=opener)

    assert not (tmp_path / "sources/source.tif").exists()
    assert (tmp_path / "sources/.source.tif.part").read_bytes() == payload


def test_candidate_download_records_identity_without_claiming_verification(
    tmp_path: Path,
) -> None:
    payload = b"candidate"

    def opener(request, *, timeout):
        return FakeResponse(
            payload, status=200, headers={"Content-Length": str(len(payload))}
        )

    receipt = download_source(
        _spec(payload, admitted=False), tmp_path / "sources", opener=opener
    )

    assert receipt["contract_verified"] is False
    assert receipt["source_status"] == "candidate"


def test_download_checks_free_space_before_streaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"candidate"

    class DiskUsage:
        free = 0

    monkeypatch.setattr(acquisition.shutil, "disk_usage", lambda path: DiskUsage())

    def opener(request, *, timeout):
        return FakeResponse(
            payload, status=200, headers={"Content-Length": str(len(payload))}
        )

    with pytest.raises(AcquisitionError, match="insufficient source-root free space"):
        download_source(
            _spec(payload, admitted=False),
            tmp_path / "sources",
            opener=opener,
            minimum_free_bytes=1,
        )

    assert not (tmp_path / "sources/source.tif").exists()
