"""Legacy Denoiser: get legacy raw files (Kodak DCS Pro Back DCR, Mamiya ZD MEF, ...) into modern denoise tools."""

import argparse
from pathlib import Path

import numpy as np


def _collect(paths: list[Path]) -> list[Path]:
    """Raw files given directly, plus supported raw files inside given folders."""
    from .cameras import EXTENSIONS

    files = []
    for p in paths:
        if p.is_dir():
            files += sorted(x for x in p.iterdir() if x.suffix.lower() in EXTENSIONS)
        else:
            files.append(p)
    if not files:
        raise SystemExit(f"No raw files found (supported: {', '.join(EXTENSIONS)})")
    return files


def main() -> None:
    from . import dng
    from .cameras import CAMERAS

    supported = ", ".join(f"{c.name.format(model='P-series')} ({'/'.join(c.extensions)})" for c in CAMERAS)
    ap = argparse.ArgumentParser(prog="legacy-denoiser", description=f"Supported cameras: {supported}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("todng", help="Convert raw files to plain DNGs (same pixels, original camera identity)")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("-o", "--outdir", type=Path)

    p = sub.add_parser("dxo", help="Only wrap raw files as Pentax 645D DNGs that DxO PureRAW accepts")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("-o", "--outdir", type=Path)
    p.add_argument("--iso", type=int, nargs="+", default=[400],
                   help="ISO written into the DNG; higher = stronger DxO denoise (several = several files)")
    p.add_argument("--full-frame", action="store_true",
                   help="Use the standard 645D crop instead of cropping to the original photo")

    p = sub.add_parser("restore", help="Only turn DxO PureRAW output back into a DNG of the original camera")
    p.add_argument("files", nargs="+", type=Path, help="DxO output DNG(s)")
    p.add_argument("--source", type=Path, help="Original raw file (default: searched next to / above the DxO file)")
    p.add_argument("-o", "--outdir", type=Path)

    p = sub.add_parser("process", help="Raw file -> DxO PureRAW -> denoised DNG, in one go")
    p.add_argument("files", nargs="+", type=Path, help="Raw files, or folders containing raw files")
    p.add_argument("-o", "--outdir", type=Path,
                   help="Where to put results (default: next to each raw file, as <name>_denoised.dng)")
    p.add_argument("--iso-factor", type=float, default=4.0,
                   help="Denoise strength: DxO sees the photo's own ISO times this (default 4, e.g. 100 -> 400)")
    p.add_argument("--iso", type=int, help="Use this fixed ISO for DxO instead of the factor")
    p.add_argument("--keep", action="store_true", help="Keep the intermediate 645D and DxO files")
    p.add_argument("--timeout", type=float, default=3600, help="Max seconds to wait for DxO")

    sub.add_parser("check", help="Check that DxO PureRAW, ExifTool etc. are ready")
    sub.add_parser("setup", help="Download ExifTool into tools/exiftool")

    args = ap.parse_args()
    if args.cmd == "setup":
        print(f"Downloading ExifTool {dng.EXIFTOOL_VERSION}...")
        print(f"Installed: {dng.install_exiftool()} (version {dng.exiftool('-ver').strip()})")
        return
    if args.cmd == "check":
        from . import dxo
        for w in dxo.preflight([Path.cwd()], 1):
            print(f"Note: {w}")
        print(f"OK: {dxo.PRODUCT} at {dxo.PURERAW_EXE}, ExifTool at {dng.EXIFTOOL}")
        print(f"Supported cameras: {supported}")
        return
    if args.cmd == "process":
        from . import dxo
        dxo.process(_collect(args.files), args.outdir, args.iso, args.iso_factor, args.keep, args.timeout)
        return
    if args.cmd == "restore":
        from . import restore
        for f in args.files:
            source = args.source or restore.find_source(f, [f.parent, f.parent.parent])
            outdir = args.outdir or f.parent
            outdir.mkdir(parents=True, exist_ok=True)
            out, m = restore.restore(f, source, outdir / f"{source.stem}_denoised.dng")
            print(f"{out}  (from {source.name}; colour gains {np.round(np.diag(m), 2)})")
        return

    for f in _collect(args.files):
        outdir = args.outdir or f.parent / "out"
        outdir.mkdir(parents=True, exist_ok=True)
        raw = dng.read_raw(f)
        if args.cmd == "todng":
            out = dng.write_plain_dng(raw, outdir / f"{f.stem}.dng")
            print(out)
        elif args.cmd == "dxo":
            for iso in args.iso:
                suffix = "_full" if args.full_frame else ""
                out = dng.write_645d_dng(raw, outdir / f"{f.stem}_645D_iso{iso}{suffix}.dng", iso,
                                         photo_crop=not args.full_frame)
                print(out)
