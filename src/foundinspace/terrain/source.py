import json
import re
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.io import MemoryFile
from rasterio.transform import Affine
from rasterio.warp import Resampling, reproject, transform_bounds

from .acquisition import digest


def metadata(dataset):
    return {
        "size": [dataset.width, dataset.height],
        "count": dataset.count,
        "dtype": dataset.dtypes[0],
        "crs": dataset.crs.to_wkt() if dataset.crs else None,
        "transform": list(dataset.transform)[:6],
        "nodata": dataset.nodata,
        "bandScale": dataset.scales[0],
        "bandOffset": dataset.offsets[0],
        "maskFlags": [
            [flag.name for flag in flags] for flags in dataset.mask_flag_enums
        ],
    }


def inspect_source(path):
    path = Path(path).resolve()
    with rasterio.open(path) as dataset:
        files = {Path(file).name: digest(file) for file in dataset.files}
        if len(files) != len(dataset.files):
            raise ValueError("Ambiguous dependency basenames")
        return {"sha256": digest(path), "metadata": metadata(dataset), "files": files}


class Source:
    def __init__(self, config, project_directory, radius):
        self.config = config
        self.read_lock = threading.Lock()
        path = (project_directory / config["file"]).resolve()
        self.spec = json.loads((project_directory / config["spec"]).read_text())
        current = inspect_source(path)
        if current != {key: self.spec[key] for key in current}:
            raise ValueError(f"Source hash/metadata mismatch: {config['id']}")
        for item in self.spec.get("evidence", []):
            if digest(path.parent / item["file"]) != item["sha256"]:
                raise ValueError(f"Source evidence changed: {item['file']}")
        if config["datum_radius_metres"] != radius:
            raise ValueError(f"Vertical datum mismatch: {config['id']}")
        self.dataset = rasterio.open(path)
        self.raw_dataset = self.dataset
        self.registered_file = None
        registration = self.spec.get("registration")
        if registration:
            if self.dataset.crs or self.dataset.transform != Affine.identity():
                raise ValueError(
                    "Registration override is only admitted for unregistered inputs"
                )
            self.crs = CRS.from_string(registration["crs"])
            self.transform = Affine(*registration["transform"])
        else:
            self.crs, self.transform = self.dataset.crs, self.dataset.transform
        if self.crs is None or self.dataset.count != 1:
            raise ValueError("Elevation requires a registered single scalar band")
        spheroid = re.search(
            r'SPHEROID\["[^"]*",([0-9.eE+-]+),([0-9.eE+-]+)', self.crs.to_wkt()
        )
        if not spheroid or float(spheroid[1]) != radius or float(spheroid[2]) != 0:
            raise ValueError("Source CRS is not the declared spherical body")
        if registration:
            # GDAL ignores a supplied transform for a rasterio Band whose
            # dataset has no affine metadata. A virtual registration attaches
            # it to the unchanged scalar band without materializing the raster.
            types = {
                "uint8": "Byte",
                "int8": "Int8",
                "uint16": "UInt16",
                "int16": "Int16",
                "uint32": "UInt32",
                "int32": "Int32",
                "float32": "Float32",
                "float64": "Float64",
            }
            root = ET.Element(
                "VRTDataset",
                rasterXSize=str(self.dataset.width),
                rasterYSize=str(self.dataset.height),
            )
            ET.SubElement(root, "SRS").text = self.crs.to_wkt()
            ET.SubElement(root, "GeoTransform").text = ",".join(
                str(value) for value in self.transform.to_gdal()
            )
            band = ET.SubElement(
                root, "VRTRasterBand", dataType=types[self.dataset.dtypes[0]], band="1"
            )
            if self.dataset.nodata is not None:
                ET.SubElement(band, "NoDataValue").text = str(self.dataset.nodata)
            simple = ET.SubElement(band, "SimpleSource")
            ET.SubElement(simple, "SourceFilename", relativeToVRT="0").text = str(path)
            ET.SubElement(simple, "SourceBand").text = "1"
            rect = {
                "xOff": "0",
                "yOff": "0",
                "xSize": str(self.dataset.width),
                "ySize": str(self.dataset.height),
            }
            ET.SubElement(simple, "SrcRect", **rect)
            ET.SubElement(simple, "DstRect", **rect)
            self.registered_file = MemoryFile(ET.tostring(root))
            self.dataset = self.registered_file.open()
        left, bottom = self.transform @ (0, self.dataset.height)
        right, top = self.transform @ (self.dataset.width, 0)
        self.projected_bounds = transform_bounds(
            self.crs,
            f"+proj=merc +R={radius} +units=m +no_defs",
            left,
            bottom,
            right,
            top,
            densify_pts=21,
        )

    def intersects(self, transform, size):
        west, south, east, north = self.projected_bounds
        left, bottom = transform @ (0, size)
        right, top = transform @ (size, 0)
        return west > east or not (
            east <= left or west >= right or north <= bottom or south >= top
        )

    def sample(self, transform, size, crs):
        # A reader may be shared by bounded tile workers, but GDAL raster handles
        # must never be used concurrently. Independent sources can run together.
        with self.read_lock:
            return self._sample(transform, size, crs)

    def _sample(self, transform, size, crs):
        values = np.full((size, size), np.nan, dtype=np.float64)
        reproject(
            rasterio.band(self.dataset, 1),
            values,
            src_transform=self.transform,
            src_crs=self.crs,
            src_nodata=self.dataset.nodata,
            dst_transform=transform,
            dst_crs=crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
            warp_mem_limit=128,
            num_threads=1,
            tolerance=0,
            XSCALE=1,
            YSCALE=1,
            init_dest_nodata=True,
        )
        return values * self.config["scale_metres"] + self.config["offset_metres"]

    def close(self):
        self.dataset.close()
        if self.raw_dataset is not self.dataset:
            self.raw_dataset.close()
        if self.registered_file:
            self.registered_file.close()
