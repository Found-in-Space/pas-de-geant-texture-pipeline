from __future__ import annotations

import json

from click.testing import CliRunner

from foundinspace.textures.cli import cli


def test_validate_project_cli_reports_product_contract(project_factory) -> None:
    project_path, _ = project_factory(maximum_zoom=2)

    result = CliRunner().invoke(cli, ["validate-project", str(project_path)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "maximum_dimension": 1024,
        "product_id": "synthetic-v1",
        "sources": ["source-a"],
        "tile_count": 21,
    }


def test_validate_project_cli_turns_contract_error_into_click_error(
    project_factory,
) -> None:
    project_path, _ = project_factory()
    project_path.write_text(
        project_path.read_text(encoding="utf-8").replace(
            "maximum_zoom = 2", 'maximum_zoom = "far"'
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["validate-project", str(project_path)])

    assert result.exit_code == 1
    assert "product.maximum_zoom must be an integer" in result.output
