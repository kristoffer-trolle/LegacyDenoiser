"""Supported legacy cameras: how to recognise their raw files and how to label the DNGs we write.

Everything else (reading the sensor data with LibRaw, the DxO disguise, restoring) is camera-independent.
To add a camera: check that LibRaw reads it, that it fits inside the Pentax 645D frame (7264x5440), and
add an entry with Adobe Camera Raw's name for it, so camera profiles and Camera Raw edits keep matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Camera:
    name: str                  # human readable
    extensions: tuple[str, ...]  # raw file extensions, lower case
    exif_model: str            # regular expression for the Model tag in the original raw file
    make: str                  # Make / Model written into our DNGs (same as the original file)
    model: str                 # "{model}" is replaced by the file's own Model tag
    unique_model: str          # Adobe Camera Raw's name for the camera (DNG UniqueCameraModel)
    iso_tag: str = "ISO"       # where the original file stores the ISO
    exif_extra: tuple[str, ...] = ()  # extra ExifTool copy arguments for this camera
    # True when Camera Raw rotates the pixels itself on opening (and the edits refer to the rotated
    # image), e.g. Phase One backs. Then the DNG stores rotated pixels with orientation "normal".
    bake_orientation: bool = False
    # True when the raw data still needs the maker's calibration (black level per row/column, flat
    # field, ...) that LibRaw only applies while processing, e.g. Phase One backs.
    libraw_corrections: bool = False


CAMERAS = [
    Camera(
        name="Kodak DCS Pro Back 645",
        extensions=(".dcr",),
        exif_model=r"ProBack645",
        make="Kodak", model="ProBack645", unique_model="Kodak ProBack645",
        iso_tag="ExposureIndex",
        exif_extra=("-EXIF:BodySerialNumber<Model2",),
    ),
    Camera(
        name="Mamiya ZD",
        extensions=(".mef",),
        exif_model=r"MAMIYA ZD",
        make="Mamiya-OP Co.,Ltd.", model="MAMIYA ZD", unique_model="Mamiya ZD",
    ),
    # P20, P21, P25, P30, P45 (and + versions). P40+ and P65+ are too large for the 645D frame.
    Camera(
        name="Phase One {model}",
        extensions=(".iiq",),
        exif_model=r"P\d\d\+?",
        make="Phase One A/S", model="{model}", unique_model="Phase One {model}",
        bake_orientation=True,
        libraw_corrections=True,
    ),
]

EXTENSIONS = sorted({ext for c in CAMERAS for ext in c.extensions})


def by_model(exif_model: str) -> Camera | None:
    """The camera entry matching a file's Model tag, with "{model}" filled in."""
    model = exif_model.strip()
    for cam in CAMERAS:
        if re.fullmatch(cam.exif_model, model, flags=re.IGNORECASE):
            return replace(cam, name=cam.name.format(model=model), model=cam.model.format(model=model),
                           unique_model=cam.unique_model.format(model=model))
    return None
