from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from foundinspace.textures.project import load_acquisition, load_project


def test_project_resolves_semantic_paths_and_computes_matrix(project_factory) -> None:
    project_path, _ = project_factory()

    project = load_project(project_path)

    assert project.target.crs_path == project_path.parent / "crs/moon.wkt"
    assert (
        project.sources[0].acquisition_path
        == project_path.parent / "sources/source.toml"
    )
    assert project.product.maximum_dimension == 2048
    assert project.product.total_tile_count == 21


def test_project_rejects_unknown_semantic_fields(project_factory) -> None:
    project_path, _ = project_factory()
    project_path.write_text(
        project_path.read_text(encoding="utf-8") + "\nunknown = true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"Unknown key\(s\) in \[product\]"):
        load_project(project_path)


def test_project_rejects_environment_and_absolute_paths(project_factory) -> None:
    project_path, _ = project_factory()
    text = project_path.read_text(encoding="utf-8")
    project_path.write_text(
        text.replace('crs = "crs/moon.wkt"', 'crs = "$CRS/moon.wkt"')
    )
    with pytest.raises(ValueError, match="environment or home expansion"):
        load_project(project_path)

    project_path.write_text(
        text.replace('crs = "crs/moon.wkt"', 'crs = "/tmp/moon.wkt"')
    )
    with pytest.raises(ValueError, match="must be relative"):
        load_project(project_path)


def test_admitted_acquisition_requires_complete_contract(tmp_path: Path) -> None:
    path = tmp_path / "source.toml"
    path.write_text(
        """
format_version = 1
status = "admitted"
source_id = "source"
title = "Source"
landing_page = "https://example.test"
url = "https://example.test/source.tif"
filename = "source.tif"
citation = "Citation"
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires source_crs and complete expected"):
        load_acquisition(path)


def test_repository_source_is_admitted_with_complete_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    spec = load_acquisition(
        root
        / "projects/moon/lroc-wac-global-100m/sources/lroc-wac-global-morphology-100m.toml"
    )

    assert spec.status == "admitted"
    assert spec.expected.complete
    assert (
        spec.expected.sha256
        == "87159ead1888ae31bb647e957ec60943022b707ec804cb5353a304575936fd55"
    )
    assert spec.expected.size_bytes == 5_959_263_751
    assert spec.source_crs is not None
    assert spec.source_crs.is_file()
    assert spec.reported["width"] == 109_164


def test_repository_wac_project_fixes_target_grid_with_admitted_source() -> None:
    root = Path(__file__).resolve().parents[1]
    project = load_project(root / "projects/moon/lroc-wac-global-100m/project.toml")

    assert project.product.maximum_dimension == 131_072
    assert project.product.total_tile_count == 87_381
    assert project.sources[0].acquisition.status == "admitted"


def test_project_semantic_identity_does_not_include_checkout_path(
    tmp_path: Path, project_factory
) -> None:
    project_path, _ = project_factory(admitted=True)
    copied_root = tmp_path / "copied-definition"
    shutil.copytree(project_path.parent, copied_root)

    original = load_project(project_path).semantic_dict()
    copied = load_project(copied_root / "project.toml").semantic_dict()

    assert original == copied
