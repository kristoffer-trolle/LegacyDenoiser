"""Supported legacy cameras: how to recognise their raw files and how to label the DNGs we write.

Everything else (reading the sensor data with LibRaw, the DxO disguise, restoring) is camera-independent.
To add a camera: check that LibRaw reads it, that it fits inside the Pentax 645D frame (7264x5440), and
add an entry with Adobe Camera Raw's name for it, so camera profiles and Camera Raw edits keep matching.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Camera:
    name: str                  # human readable
    extensions: tuple[str, ...]  # raw file extensions, lower case
    exif_model: str            # the Model tag in the original raw file
    make: str                  # Make / Model written into our DNGs (same as the original file)
    model: str
    unique_model: str          # Adobe Camera Raw's name for the camera (DNG UniqueCameraModel)
    iso_tag: str = "ISO"       # where the original file stores the ISO
    exif_extra: tuple[str, ...] = ()  # extra ExifTool copy arguments for this camera


CAMERAS = [
    Camera(
        name="Kodak DCS Pro Back 645",
        extensions=(".dcr",),
        exif_model="ProBack645",
        make="Kodak", model="ProBack645", unique_model="Kodak ProBack645",
        iso_tag="ExposureIndex",
        exif_extra=("-EXIF:BodySerialNumber<Model2",),
    ),
    Camera(
        name="Mamiya ZD",
        extensions=(".mef",),
        exif_model="MAMIYA ZD",
        make="Mamiya-OP Co.,Ltd.", model="MAMIYA ZD", unique_model="Mamiya ZD",
    ),
]

EXTENSIONS = sorted({ext for c in CAMERAS for ext in c.extensions})


def by_model(exif_model: str) -> Camera | None:
    for cam in CAMERAS:
        if cam.exif_model.lower() == exif_model.strip().lower():
            return cam
    return None
