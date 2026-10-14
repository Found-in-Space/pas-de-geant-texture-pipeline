"""Build and validate five Apollo imagery products, then collect all six sites.

Run acquire_imagery.py first. Raw sources, metadata, recipes, logs, authoring
products and final products remain on the persistent data volume. Successful
site products are reusable if a later site fails; inputs are immutable.
"""

import argparse
import json
import shutil
import subprocess
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from foundinspace.textures.util import atomic_write_json, sha256_file, utc_now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--apollo11-root", type=Path, required=True)
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument(
        "--wait-for-sources",
        action="store_true",
        help="Build each site once its verified raw inputs have arrived (up to six hours).",
    )
    args = parser.parse_args()
    root = args.data_root.resolve()
    if not root.is_relative_to("/data"):
        raise ValueError("Use the persistent /data volume")
    run = root / "runs/surfaces" / args.run_id
    raw = root / "raw/surfaces/moon" / args.run_id
    final = root / "derived/surfaces/moon" / args.run_id
    final.mkdir(parents=True, exist_ok=True)
    if not args.wait_for_sources:
        acquisition = json.loads((run / "acquisition/sources.json").read_text())
        if acquisition["status"] != "complete":
            raise ValueError("Source acquisition must complete before production")
    plan = json.loads((run / "acquisition/plan.json").read_text())
    lock = threading.Lock()
    repository = Path(__file__).resolve().parents[2]

    def command(argv, log):
        with lock, (run / "commands.jsonl").open("a") as stream:
            stream.write(json.dumps({"argv": argv, "startedAt": utc_now()}) + "\n")
        with log.open("w") as stream:
            subprocess.run(
                ["uv", "run", "pas-de-geant-textures", *argv],
                cwd=repository,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=True,
            )

    def build(entry):
        mission = entry["mission"]
        site = run / f"apollo{mission}"
        site.mkdir(exist_ok=True)
        project = (
            Path(__file__).parent / f"apollo{mission}-preview-mercator-v2/preview.toml"
        )
        if sha256_file(project) != entry["sha256"]:
            raise ValueError("Recipe changed since source preflight")
        deadline = time.monotonic() + 6 * 3600
        for specification in entry["recipe"]["context_sources"]:
            path = raw / (specification["stem"] + ".img")
            receipt = path.with_suffix(".img.receipt.json")
            while not (path.exists() and receipt.exists()):
                if not args.wait_for_sources or time.monotonic() >= deadline:
                    raise ValueError(f"Verified source has not arrived: {path.name}")
                time.sleep(5)
            record = json.loads(receipt.read_text())
            if (
                record["url"] != specification["url"]
                or record["bytes"] != 10800 * 10800 * 2
                or record["sha256"] != sha256_file(path)
            ):
                raise ValueError(f"Verified source changed: {path.name}")
        product = final / f"apollo{mission}"
        if product.exists():
            record = json.loads((product / "product.json").read_text())
            if record["preview"]["recipe"] != entry["recipe"]:
                raise ValueError("Existing product recipe differs from this run")
            command(
                ["validate-preview-tiles", str(product)], site / "validate-resume.log"
            )
            print(f"Apollo {mission}: reused validated product", flush=True)
            return mission, product
        if shutil.disk_usage(root).free < 20_000_000_000:
            raise ValueError("Less than 20 GB free before site build")
        preview = site / "preview"
        if not (preview / "product.json").exists():
            print(f"Apollo {mission}: building 100 km Kaguya context", flush=True)
            command(
                [
                    "build-preview",
                    str(project.resolve()),
                    "--source-root",
                    str(raw),
                    "--detail-root",
                    str(run / "metadata"),
                    "--work-root",
                    str(site / "work"),
                    "--output-root",
                    str(preview),
                ],
                site / "build-preview.log",
            )
        elif json.loads((preview / "product.json").read_text())[
            "recipe"
        ] != tomllib.loads(project.read_text()):
            raise ValueError("Authoring recipe changed")
        runtime = site / "runtime"
        if not (runtime / "product.json").exists():
            print(f"Apollo {mission}: acquiring and preparing NAC tiles", flush=True)
            argv = [
                "prepare-preview-tiles",
                str(preview),
                "--source-root",
                str(run / "archive-tiles"),
                "--output-root",
                str(runtime),
                "--download-concurrency",
                "8",
            ]
            if args.allow_download:
                argv += ["--allow-download"]
            command(argv, site / "prepare-runtime.log")
        command(["validate-preview-tiles", str(runtime)], site / "validate-runtime.log")
        runtime.rename(product)
        report = json.loads((product / "validation.json").read_text())
        print(
            f"Apollo {mission}: promoted {report['tileCount']} validated tiles",
            flush=True,
        )
        return mission, product

    atomic_write_json(
        run / "build-state.json", {"status": "building", "startedAt": utc_now()}
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            products = list(executor.map(build, plan["recipes"]))
        collection = final / "all-sites"
        if not collection.exists():
            argv = [
                "collect-preview-tiles",
                "--input",
                "apollo11",
                str(args.apollo11_root.resolve()),
            ]
            for mission, path in sorted(products):
                argv += ["--input", f"apollo{mission}", str(path)]
            argv += ["--output-root", str(collection)]
            command(argv, run / "collect.log")
        else:
            command(
                ["validate-preview-tiles", str(collection)],
                run / "validate-collection.log",
            )
        report = json.loads((collection / "validation.json").read_text())
        atomic_write_json(
            run / "build-state.json",
            {
                "status": "complete",
                "completedAt": utc_now(),
                "collection": str(collection),
                "validation": report,
            },
        )
        print(
            f"All six sites: {report['tileCount']} validated tiles at {collection}",
            flush=True,
        )
    except Exception as error:
        atomic_write_json(
            run / "build-state.json",
            {"status": "failed", "failedAt": utc_now(), "error": str(error)},
        )
        raise


if __name__ == "__main__":
    main()
