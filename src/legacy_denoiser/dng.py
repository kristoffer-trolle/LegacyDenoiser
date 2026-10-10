"""Read legacy raw files with LibRaw and write them back out as DNGs."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import numpy as np
import rawpy
import tifffile

from .cameras import Camera, by_model

ROOT = Path(__file__).resolve().parents[2]
EXIFTOOL = ROOT / "tools" / "exiftool" / "exiftool.exe"

# CFA colour indices as used in DNG: 0=R, 1=G, 2=B
_LIBRAW_TO_DNG = {"R": 0, "G": 1, "B": 2}

# CIE XYZ of the D65 white point, used when a file has no white balance of its own
_XYZ_D65 = np.array([0.95047, 1.0, 1.08883])

# Pentax 645D identity (from a real 645D DNG). Kodak KAF-40000 CCD, supported by DxO.
PENTAX_645D = dict(
    make="PENTAX",
    model="PENTAX 645D",
    software="645D Ver 1.31",
    width=7424,
    height=5552,
    cfa=(2, 1, 1, 0),  # BGGR
    white=15767,
    crop_origin=(80, 59),  # x, y
    crop_size=(7264, 5440),
    color_matrix1=[1.171905518, -0.5433349609, -0.1468963623, -0.4726715088, 1.229431152,
                   0.2743530273, -0.06729125977, 0.1534729004, 0.7498626709],
    color_matrix2=[0.9813537598, -0.2716217041, -0.1439208984, -0.5049133301, 1.390701294,
                   0.1165771484, -0.183013916, 0.3836212158, 0.5705566406],
)


class UnsupportedCamera(ValueError):
    pass


@dataclass
class RawImage:
    path: Path
    camera: Camera
    cfa: np.ndarray            # (H, W) uint16 linear sensor values, as stored (not rotated)
    pattern: tuple[int, ...]   # DNG CFA pattern for the top-left 2x2, e.g. (1, 0, 2, 1) = GRBG
    black: int
    white: int
    color_matrix: list[float]  # XYZ(D65) -> camera, row major 3x3
    as_shot_neutral: list[float]
    crop: tuple[int, int, int, int]  # x, y, w, h of the valid image area
    orientation: int           # EXIF orientation of the original file (1 = as stored)
    iso: int
    preview: np.ndarray = field(repr=False, default=None)  # small sRGB render, not rotated


def read_metadata(path: Path) -> dict:
    return json.loads(exiftool("-j", "-n", "-Model", "-Orientation", "-ISO", "-ExposureIndex", str(path)))[0]


def read_raw(path: str | Path) -> RawImage:
    path = Path(path)
    meta = read_metadata(path)
    camera = by_model(str(meta.get("Model", "")))
    if camera is None:
        raise UnsupportedCamera(f"unsupported camera '{meta.get('Model', 'unknown')}'")
    orientation = meta.get("Orientation")
    orientation = orientation if isinstance(orientation, int) and 1 <= orientation <= 8 else 1
    iso = meta.get(camera.iso_tag) or meta.get("ISO") or 100

    with rawpy.imread(str(path)) as r:
        desc = r.color_desc.decode()
        pattern = tuple(_LIBRAW_TO_DNG[desc[i]] for i in r.raw_pattern.flatten())
        cfa = r.raw_image_visible.copy()
        color_matrix = np.array(r.rgb_xyz_matrix[:3], dtype=np.float64)
        cam_mul = np.array(r.camera_whitebalance[:3], dtype=np.float64)
        has_wb = bool(np.all(cam_mul > 0))
        if has_wb:
            neutral = cam_mul[1] / cam_mul
        else:  # no white balance in the file: use daylight (D65) as "as shot"
            neutral = color_matrix @ _XYZ_D65
        neutral /= neutral.max()
        s = r.sizes
        crop = (s.crop_left_margin, s.crop_top_margin, s.crop_width, s.crop_height)
        if crop[2] <= 0 or crop[3] <= 0:
            crop = (0, 0, cfa.shape[1], cfa.shape[0])
        preview = r.postprocess(use_camera_wb=has_wb, half_size=True, output_bps=8, user_flip=0)
        return RawImage(
            path=path,
            camera=camera,
            cfa=cfa,
            pattern=pattern,
            black=int(r.black_level_per_channel[0]),
            white=int(r.white_level),
            color_matrix=[float(v) for v in color_matrix.flatten()],
            as_shot_neutral=[float(v) for v in neutral],
            crop=crop,
            orientation=orientation,
            iso=int(round(float(iso))),
            preview=preview,
        )


def _rationals(values, signed=False):
    out = []
    for v in values:
        f = Fraction(float(v)).limit_denominator(10000)
        out += [f.numerator, f.denominator]
    return out


def _thumbnail(rgb8: np.ndarray, size: int = 256) -> np.ndarray:
    step = max(1, max(rgb8.shape[:2]) // size)
    return np.ascontiguousarray(rgb8[::step, ::step])


def _write_dng(out: Path, cfa: np.ndarray, *, make, model, unique_model, software, pattern,
               black, white, crop_origin, crop_size, color_matrix1, color_matrix2=None,
               as_shot_neutral, thumbnail, baseline_exposure=0.0, orientation=1):
    ifd0_tags = [
        (271, 2, 0, make, True),
        (272, 2, 0, model, True),
        (274, 3, 1, orientation, True),  # Orientation
        (50706, 1, 4, (1, 4, 0, 0), True),  # DNGVersion
        (50707, 1, 4, (1, 1, 0, 0), True),  # DNGBackwardVersion
        (50708, 2, 0, unique_model, True),  # UniqueCameraModel
        (50721, 10, 9, _rationals(color_matrix1), True),  # ColorMatrix1
        (50728, 5, 3, _rationals(as_shot_neutral), True),  # AsShotNeutral
        (50730, 10, 1, _rationals([baseline_exposure]), True),  # BaselineExposure
        (50778, 3, 1, 21 if color_matrix2 is None else 17, True),  # CalibrationIlluminant1
    ]
    if color_matrix2 is not None:
        ifd0_tags += [
            (50722, 10, 9, _rationals(color_matrix2), True),  # ColorMatrix2
            (50779, 3, 1, 21, True),  # CalibrationIlluminant2 = D65
        ]
    linear = cfa.ndim == 3  # demosaiced (LinearRaw) RGB instead of a Bayer mosaic
    n = 3 if linear else 1
    raw_tags = [
        (50713, 3, 2, (1, 1), True),  # BlackLevelRepeatDim
        (50714, 4, n, (int(black),) * n, True),  # BlackLevel
        (50717, 4, n, (int(white),) * n, True),  # WhiteLevel
        (50719, 4, 2, tuple(int(v) for v in crop_origin), True),  # DefaultCropOrigin
        (50720, 4, 2, tuple(int(v) for v in crop_size), True),  # DefaultCropSize
    ]
    if not linear:
        raw_tags += [
            (33421, 3, 2, (2, 2), True),  # CFARepeatPatternDim
            (33422, 1, 4, tuple(pattern), True),  # CFAPattern
            (50710, 1, 3, (0, 1, 2), True),  # CFAPlaneColor
            (50711, 3, 1, 1, True),  # CFALayout rectangular
        ]
    with tifffile.TiffWriter(out, bigtiff=False, byteorder="<") as tif:
        tif.write(thumbnail, photometric="rgb", subfiletype=1, subifds=1, software=software,
                  extratags=ifd0_tags, metadata=None)
        # tifffile doesn't know LinearRaw and would tag 2 of the 3 channels as ExtraSamples (which
        # Adobe Camera Raw rejects), so write it as RGB and patch the photometric value afterwards.
        tif.write(cfa.astype(np.uint16), photometric="rgb" if linear else 32803, subfiletype=0,
                  planarconfig="contig" if linear else None, extratags=raw_tags, metadata=None,
                  compression=None, rowsperstrip=256, software=False)
    if linear:
        with tifffile.TiffFile(out, mode="r+b") as tf:
            tf.pages[0].pages[0].tags[262].overwrite(34892)


EXIFTOOL_VERSION = "13.59"


def install_exiftool() -> Path:
    """Download the portable Windows ExifTool into tools/exiftool (it is not stored in git)."""
    import io
    import shutil
    import urllib.request
    import zipfile

    name = f"exiftool-{EXIFTOOL_VERSION}_64"
    url = f"https://sourceforge.net/projects/exiftool/files/{name}.zip/download"
    with urllib.request.urlopen(url) as resp:
        data = resp.read()
    target = EXIFTOOL.parent
    shutil.rmtree(target, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.infolist():
            rel = Path(member.filename).relative_to(name) if member.filename.startswith(name + "/") else None
            if rel is None or member.is_dir() or ".." in rel.parts:
                continue
            dest = target / ("exiftool.exe" if rel.name == "exiftool(-k).exe" else rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(member))
    return EXIFTOOL


def exiftool(*args: str) -> str:
    res = subprocess.run([str(EXIFTOOL), *args], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or res.stdout.strip())
    return res.stdout


def copy_exif(raw: RawImage, dst: Path, extra: list[str] = ()):
    """Copy shooting metadata (exposure, lens, artist, ...) from the original file into the DNG's EXIF."""
    iso = "-ISO" if raw.camera.iso_tag == "ISO" else f"-EXIF:ISO<{raw.camera.iso_tag}"
    exiftool(
        "-q", "-q", "-overwrite_original", "-m",
        "-tagsFromFile", str(raw.path),
        "-ExposureTime", "-FNumber", "-ExposureProgram", "-ExposureCompensation", "-ExposureMode",
        "-FocalLength", "-FocalLengthIn35mmFormat", "-MeteringMode", "-LightSource", "-EXIF:Flash",
        "-Artist", "-Copyright", "-ImageNumber", "-DateTimeOriginal", "-CreateDate",
        "-LensModel", "-SerialNumber",
        iso, *raw.camera.exif_extra,
        *extra,
        str(dst),
    )


def find_sidecar(raw_file: Path) -> Path | None:
    """Camera Raw keeps edits of a raw file in a sidecar '<name>.xmp' next to it."""
    for cand in raw_file.parent.glob(raw_file.stem + ".*"):
        if cand.suffix.lower() == ".xmp":
            return cand
    return None


def embed_edits(raw_file: Path, dst: Path) -> Path | None:
    """Put the raw file's Camera Raw edits (sidecar XMP) inside the DNG, where Camera Raw reads them for DNGs.

    Noise reduction is reset to 0 because the image is already denoised.
    """
    xmp = find_sidecar(raw_file)
    if xmp is None:
        return None
    exiftool("-q", "-q", "-overwrite_original", "-m", f"-xmp<={xmp}", str(dst))
    exiftool("-q", "-q", "-overwrite_original", "-m",
             "-XMP-crs:LuminanceSmoothing=0", "-XMP-crs:ColorNoiseReduction=0",
             "-XMP-crs:RawFileName=", "-XMP-dc:Format=image/dng", str(dst))
    return xmp


def write_plain_dng(raw: RawImage, out: Path, cfa: np.ndarray | None = None) -> Path:
    """An honest DNG: original camera identity, original pixel grid, Adobe colour matrix."""
    x, y, w, h = raw.crop
    cam = raw.camera
    _write_dng(
        out, raw.cfa if cfa is None else cfa,
        make=cam.make, model=cam.model, unique_model=cam.unique_model,
        software="Legacy Denoiser", pattern=raw.pattern,
        black=raw.black, white=raw.white,
        crop_origin=(x, y), crop_size=(w, h),
        color_matrix1=raw.color_matrix, as_shot_neutral=raw.as_shot_neutral,
        thumbnail=_thumbnail(raw.preview), orientation=raw.orientation,
    )
    copy_exif(raw, out)
    embed_edits(raw.path, out)
    return out


def placement_645d(raw: RawImage) -> tuple[int, int]:
    """Top-left (y, x) where the photo is pasted into the 645D frame so CFA colours line up."""
    p = PENTAX_645D
    H, W = raw.cfa.shape
    cx, cy = p["crop_origin"]
    cw, ch = p["crop_size"]
    if H > ch - 2 or W > cw - 2:
        raise UnsupportedCamera(f"{W}x{H} sensor is too large for the Pentax 645D frame ({cw}x{ch})")
    y0 = cy + (ch - H) // 2
    x0 = cx + (cw - W) // 2
    target = np.array(p["cfa"]).reshape(2, 2)
    for dy in range(2):
        for dx in range(2):
            if tuple(np.roll(target, (-(y0 + dy), -(x0 + dx)), (0, 1)).flatten()) == raw.pattern:
                return y0 + dy, x0 + dx
    raise ValueError("CFA patterns cannot be aligned")


def write_645d_dng(raw: RawImage, out: Path, iso: int, cfa: np.ndarray | None = None,
                   photo_crop: bool = True) -> Path:
    """Disguise the photo as a Pentax 645D DNG so DxO PureRAW will accept it.

    The sensor data is placed in the middle of a 7424x5552 645D frame (aligned so the Bayer colours
    match) and the surroundings are filled with a mirror image of the photo, which keeps the denoiser
    free of edge artifacts. With `photo_crop` the DNG's DefaultCrop points at the photo only, so
    viewers show just the original image; otherwise the standard 645D crop is used. Pixels stay
    unrotated (orientation is restored afterwards). Values are scaled to the 645D white level.
    `iso` steers DxO's denoise strength.
    """
    p = PENTAX_645D
    src = (raw.cfa if cfa is None else cfa).astype(np.float32)
    scale = (p["white"] - 0) / (raw.white - raw.black)
    src = (src - raw.black) * scale
    y0, x0 = placement_645d(raw)
    H, W = src.shape
    canvas = np.pad(src, ((y0, p["height"] - H - y0), (x0, p["width"] - W - x0)), mode="reflect")
    canvas = np.clip(np.rint(canvas), 0, p["white"]).astype(np.uint16)

    if photo_crop:
        # Snap the crop to the 2x2 CFA grid (some raw readers round odd origins), staying inside the image
        cx, cy, cw, ch = raw.crop
        ox, oy = x0 + cx + (x0 + cx) % 2, y0 + cy + (y0 + cy) % 2
        cw -= ox - (x0 + cx)
        ch -= oy - (y0 + cy)
        crop_origin, crop_size = (ox, oy), (cw - cw % 2, ch - ch % 2)
    else:
        crop_origin, crop_size = p["crop_origin"], p["crop_size"]

    _write_dng(
        out, canvas,
        make=p["make"], model=p["model"], unique_model=p["model"], software=p["software"],
        pattern=p["cfa"], black=0, white=p["white"],
        crop_origin=crop_origin, crop_size=crop_size,
        color_matrix1=p["color_matrix1"], color_matrix2=p["color_matrix2"],
        as_shot_neutral=raw.as_shot_neutral,
        thumbnail=_thumbnail(raw.preview),
        baseline_exposure=-0.5555267334,
    )
    copy_exif(raw, out, extra=[f"-EXIF:ISO={iso}", "-EXIF:BodySerialNumber=", "-EXIF:SerialNumber="])
    return out
