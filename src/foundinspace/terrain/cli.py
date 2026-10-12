import argparse
import json
from pathlib import Path

from .acquisition import acquire_file, acquire_grid_window, write_json
from .build import build, load_project, validate
from .grid import addresses, availability
from .source import inspect_source


def main():
    parser = argparse.ArgumentParser(
        description="Controlled planetary elevation production"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("project", type=Path)
    inspection = commands.add_parser("inspect")
    inspection.add_argument("source", type=Path)
    inspection.add_argument("--output", type=Path)
    creation = commands.add_parser("build")
    creation.add_argument("project", type=Path)
    creation.add_argument("--output", type=Path, required=True)
    checking = commands.add_parser("validate")
    checking.add_argument("output", type=Path)
    acquire = commands.add_parser("acquire")
    acquire.add_argument("url")
    acquire.add_argument("--bytes", type=int, required=True)
    acquire.add_argument("--output", type=Path, required=True)
    window = commands.add_parser("acquire-window")
    window.add_argument("spec", type=Path)
    window.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        project = load_project(args.project)
        coverage = availability(project)
        result = {
            "availability": coverage,
            "tileCount": sum(1 for _ in addresses(coverage)),
            "uncompressedTileBytes": project["tile_size"] ** 2 * 3,
        }
    elif args.command == "inspect":
        result = inspect_source(args.source)
        if args.output:
            write_json(args.output, result)
    elif args.command == "build":
        result = build(args.project, args.output)
    elif args.command == "validate":
        result = validate(args.output)
    elif args.command == "acquire":
        result = acquire_file(args.url, args.output, args.bytes)
    else:
        result = acquire_grid_window(json.loads(args.spec.read_text()), args.output)
    print(json.dumps(result, indent=2, allow_nan=False))
