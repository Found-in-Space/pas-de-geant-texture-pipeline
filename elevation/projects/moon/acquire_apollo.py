"""Discover exact public LROC objects, then resume authenticated acquisitions."""

import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from foundinspace.terrain.acquisition import acquire_file, digest, write_json

MISSIONS = (11, 12, 14, 15, 16, 17)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".cache/sources"))
    parser.add_argument("--discover-only", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    inventory_path = args.output / "apollo-acquisition.json"
    if inventory_path.exists():
        inventory = json.loads(inventory_path.read_text())
    else:
        inventory = []
        for mission in MISSIONS:
            page_url = f"https://data.lroc.im-ldi.com/lroc/view_rdr_product/NAC_DTM_APOLLO{mission}"
            with urllib.request.urlopen(page_url, timeout=60) as response:
                page = response.read()
            page_path = args.output / f"apollo{mission}.html"
            page_path.write_bytes(page)
            links = [
                urllib.parse.urljoin(page_url, value.decode())
                for value in re.findall(rb'href=["\']([^"\']+)["\']', page)
            ]
            tif = next(
                value
                for value in links
                if value.upper().endswith(f"NAC_DTM_APOLLO{mission}.TIF")
            )
            label = next(
                value
                for value in links
                if value.upper().endswith(f"NAC_DTM_APOLLO{mission}.LBL")
            )
            request = urllib.request.Request(
                tif, headers={"Range": "bytes=0-0", "Accept-Encoding": "identity"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 206 or not re.fullmatch(
                    r"bytes 0-0/\d+", response.headers.get("Content-Range", "")
                ):
                    raise ValueError("Archive does not support declared byte ranges")
                size = int(response.headers["Content-Range"].split("/")[1])
                resolved = response.url
            inventory.append(
                {
                    "mission": mission,
                    "url": resolved,
                    "bytes": size,
                    "labelUrl": label,
                    "pageUrl": page_url,
                    "pageSha256": digest(page_path),
                }
            )
        write_json(inventory_path, inventory)
    print(
        f"Declared DTM payload: {sum(item['bytes'] for item in inventory)} bytes",
        flush=True,
    )
    if args.discover_only:
        return
    for item in inventory:
        mission = item["mission"]
        acquire_file(item["url"], args.output / f"apollo{mission}.tif", item["bytes"])
        for name, url in [
            (f"apollo{mission}.lbl", item["labelUrl"]),
            (
                f"apollo{mission}-readme.txt",
                item["labelUrl"].replace(".LBL", "_README.TXT"),
            ),
        ]:
            path = args.output / name
            if not path.exists():
                with urllib.request.urlopen(url, timeout=60) as response:
                    path.write_bytes(response.read())
        print(f"Authenticated Apollo {mission}", flush=True)
    base = "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/sldem2015/tiles/float_img"
    for stem in (
        "sldem2015_512_00n_30n_000_045_float",
        "sldem2015_512_30s_00s_000_045_float",
        "sldem2015_512_30s_00s_315_360_float",
    ):
        path = args.output / f"{stem}.lbl"
        if not path.exists():
            with urllib.request.urlopen(f"{base}/{stem}.lbl", timeout=60) as response:
                path.write_bytes(response.read())


if __name__ == "__main__":
    main()
