"""Turn DxO PureRAW output of a 645D-disguised DNG back into a DNG of the original camera."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import tifffile

from . import dng
from .cameras import EXTENSIONS

# XYZ (D65) -> linear sRGB
_XYZ_TO_SRGB = np.array([[3.2404542, -1.5371385, -0.4985314],
                         [-0.9692660, 1.8760108, 0.0415560],
                         [0.0556434, -0.2040259, 1.0572252]])


def find_source(dxo_file: Path, search_dirs: list[Path]) -> Path:
    """DxO names its output '<stem>_645D_iso400-dng_DxO_DeepPRIME.dng'; find the raw file '<stem>.*'."""
    stem = re.split(r"_645D_iso\d+", dxo_file.stem)[0]
    for d in search_dirs:
        for cand in d.iterdir():
            if cand.stem == stem and cand.suffix.lower() in EXTENSIONS:
                return cand
    raise FileNotFoundError(f"Could not find the raw file for {stem} in {', '.join(map(str, search_dirs))}")


def read_linear_dng(path: Path) -> np.ndarray:
    with tifffile.TiffFile(path) as tf:
        for page in [tf.pages[0], *tf.pages[0].pages]:
            if page.photometric == 34892 and page.samplesperpixel == 3:
                return page.asarray()
    raise ValueError(f"{path} has no LinearRaw RGB image (is it a DxO DNG output?)")


def _bayer_rgb(cfa: np.ndarray, pattern: tuple[int, ...]) -> np.ndarray:
    """Average each 2x2 Bayer block into one R, G, B pixel (half resolution, no demosaic)."""
    planes = [cfa[dy::2, dx::2].astype(np.float64) for dy in (0, 1) for dx in (0, 1)]
    out = np.zeros(planes[0].shape + (3,))
    for colour, plane in zip(pattern, planes):
        out[..., colour] += plane
    out[..., 1] /= 2
    return out


def fit_colour_transform(camera_rgb: np.ndarray, dxo_rgb: np.ndarray, white: int, block: int = 8) -> np.ndarray:
    """Least-squares 3x3 matrix M with dxo ≈ camera @ M, fitted on block averages to beat the noise."""
    h, w = (s // block * block for s in camera_rgb.shape[:2])
    shape = (h // block, block, w // block, block, 3)
    k = camera_rgb[:h, :w].reshape(shape)
    kb, db = k.mean(axis=(1, 3)), dxo_rgb[:h, :w].reshape(shape).mean(axis=(1, 3))
    ok = (k.max(axis=(1, 3, 4)) < 0.93 * white) & (kb.min(-1) > 0.001 * white)
    if ok.sum() < 500:
        raise ValueError("Too few usable pixels to calibrate colours")
    m, *_ = np.linalg.lstsq(kb[ok], db[ok], rcond=None)
    return m


def render_srgb8(cam_rgb: np.ndarray, color_matrix: list[float], neutral: list[float], white: float) -> np.ndarray:
    """Quick camera RGB -> sRGB render, only used for the embedded thumbnail."""
    cam_to_xyz = np.linalg.inv(np.array(color_matrix).reshape(3, 3))
    img = cam_rgb / white / np.array(neutral)
    xyz = img @ cam_to_xyz.T
    xyz /= (cam_to_xyz @ np.ones(3))[1]
    rgb = np.clip(xyz @ _XYZ_TO_SRGB.T, 0, None)
    rgb = rgb / max(np.percentile(rgb, 99.5), 1e-6)
    rgb = np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * np.power(np.clip(rgb, 0, 1), 1 / 2.4) - 0.055)
    return (np.clip(rgb, 0, 1) * 255).astype(np.uint8)


def restore(dxo_file: Path, raw_file: Path, out: Path) -> tuple[Path, np.ndarray]:
    raw = dng.read_raw(raw_file)
    big = read_linear_dng(dxo_file)
    p = dng.PENTAX_645D
    if big.shape[:2] == (p["crop_size"][1], p["crop_size"][0]):
        oy, ox = p["crop_origin"][1], p["crop_origin"][0]
    elif big.shape[:2] == (p["height"], p["width"]):
        oy, ox = 0, 0
    else:
        raise ValueError(f"Unexpected DxO output size {big.shape[1]}x{big.shape[0]}")

    y0, x0 = dng.placement_645d(raw)
    H, W = raw.cfa.shape
    full = big[y0 - oy:y0 - oy + H, x0 - ox:x0 - ox + W].astype(np.float64)

    # Map DxO's channels back onto the original camera RGB (removes DxO's gain + slight mixing)
    half = full.reshape(H // 2, 2, W // 2, 2, 3).mean(axis=(1, 3))
    span = raw.white - raw.black
    m = fit_colour_transform(_bayer_rgb(raw.cfa, raw.pattern) - raw.black, half, span)
    out_white = 65535
    to_camera = np.linalg.inv(m) * (out_white / span)

    cx, cy, cw, ch = raw.crop
    img = full[cy:cy + ch, cx:cx + cw] @ to_camera
    img = np.clip(np.rint(img), 0, out_white).astype(np.uint16)

    thumb = render_srgb8(img[::16, ::16].astype(np.float64), raw.color_matrix, raw.as_shot_neutral, out_white)
    dng._write_dng(
        out, img,
        make=raw.camera.make, model=raw.camera.model, unique_model=raw.camera.unique_model,
        software="DxO PureRAW + Legacy Denoiser", pattern=None,
        black=0, white=out_white, crop_origin=(0, 0), crop_size=(cw, ch),
        color_matrix1=raw.color_matrix, as_shot_neutral=raw.as_shot_neutral,
        thumbnail=thumb, orientation=raw.orientation,
    )
    dng.copy_exif(raw, out)
    dng.embed_edits(raw.path, out)
    return out, m
