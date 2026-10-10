"""Drive DxO PureRAW 3: hand it disguised DNGs, wait for its output, restore the results."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import time
import winreg
from pathlib import Path

from . import dng, restore

_DXO_DIR = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "DxO"
TESTED_VERSION = 3
MB_PER_PHOTO = 350  # disguised DNG (~80) + DxO output (~125) + result (~100), with margin


def _find_install() -> tuple[str, Path] | None:
    """Newest 'DxO PureRAW N' folder and its main exe, e.g. ('DxO PureRAW 3', .../PureRawv3.exe)."""
    found = []
    for folder in _DXO_DIR.glob("DxO PureRAW*"):
        exes = [e for e in folder.glob("PureRaw*.exe") if "saver" not in e.name.lower()]
        if exes:
            m = re.search(r"(\d+)$", folder.name)
            found.append((int(m.group(1)) if m else 0, folder.name, exes[0]))
    if not found:
        return None
    _, name, exe = max(found)
    return name, exe


_INSTALL = _find_install()
PRODUCT, PURERAW_EXE = _INSTALL if _INSTALL else ("DxO PureRAW 3", _DXO_DIR / "DxO PureRAW 3" / "PureRawv3.exe")
_REG_KEY = rf"Software\DxO\{PRODUCT}"
CAMERA_DB = Path(os.environ.get("LOCALAPPDATA", "")) / "DxO_Labs" / PRODUCT / "Modules" / "CAFList.db"


def _reg(name: str, default=None):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


def output_dirs(input_dir: Path) -> list[Path]:
    """Folders where PureRAW may write its results, based on its destination settings."""
    dirs = [input_dir]
    if str(_reg("useCustomDestinationFolder", "false")).lower() == "true":
        dirs.insert(0, Path(_reg("customDestinationFolder", "")))
    sub = _reg("destinationSubfolderName", "DxO") or "DxO"
    dirs += [d / sub for d in list(dirs)]
    return dirs


def puraw_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {PURERAW_EXE.name}", "/NH"],
                         capture_output=True, text=True).stdout
    return PURERAW_EXE.name.lower() in out.lower()


def preflight(work_dirs: list[Path], n_photos: int) -> list[str]:
    """Check everything the pipeline needs. Returns warnings; raises SystemExit on blocking problems."""
    errors, warnings = [], []
    if _INSTALL is None:
        errors.append(f"DxO PureRAW is not installed (looked in {_DXO_DIR}).")
    else:
        version = re.search(r"(\d+)$", PRODUCT)
        if version and int(version.group(1)) != TESTED_VERSION:
            warnings.append(f"Found {PRODUCT}; this tool was only tested with DxO PureRAW {TESTED_VERSION}.")
        if not CAMERA_DB.exists():
            warnings.append("DxO's camera list was not found; start PureRAW once so it downloads it.")
        else:
            try:
                with sqlite3.connect(f"file:{CAMERA_DB}?mode=ro", uri=True) as db:
                    if not db.execute("select 1 from Body where id='Pentax645D'").fetchone():
                        errors.append(f"{PRODUCT} does not support the Pentax 645D, which this tool relies on.")
            except sqlite3.Error as e:
                warnings.append(f"Could not read DxO's camera list ({e}).")
        if puraw_running():
            errors.append("Please close DxO PureRAW first (it only accepts new files when started fresh).")
    if not dng.EXIFTOOL.exists():
        errors.append(f"ExifTool is missing: {dng.EXIFTOOL}")
    for d in work_dirs:
        free_mb = shutil.disk_usage(d).free / 2**20
        need_mb = MB_PER_PHOTO * n_photos
        if free_mb < need_mb:
            errors.append(f"Not enough disk space on {d.resolve().anchor}: {free_mb:.0f} MB free, about {need_mb} MB needed.")
    if errors:
        raise SystemExit("Cannot start:\n  - " + "\n  - ".join(errors))
    return warnings


def launch(files: list[Path], batch_file: Path) -> subprocess.Popen:
    """Open PureRAW's 'Process N photos' dialog for these files (the way its Lightroom plugin does)."""
    batch_file.write_text("".join(f"{f.resolve()}\n" for f in files), encoding="utf-8")
    return subprocess.Popen([str(PURERAW_EXE), "--as-lightroom-plugin", '--lr-version="13.0"',
                             f"--batch-file={batch_file}"])


def find_output(src: Path, dirs: list[Path]) -> Path | None:
    for d in dirs:
        if d.is_dir():
            for cand in d.glob(f"{src.stem}-dng_DxO_*.dng"):
                return cand
    return None


def non_dng_outputs(src: Path, dirs: list[Path]) -> list[Path]:
    """JPG/TIFF results DxO made for this file (useless to us: only DNG keeps the raw data)."""
    return [c for d in dirs if d.is_dir() for c in d.glob(f"{src.stem}-dng_DxO_*")
            if c.suffix.lower() != ".dng"]


def _is_finished(path: Path, sizes: dict[Path, int]) -> bool:
    """A file counts as written once its size has stopped changing between two polls."""
    size = path.stat().st_size
    done = size > 0 and sizes.get(path) == size
    sizes[path] = size
    return done


def process(raw_files: list[Path], outdir: Path | None, iso: int | None, iso_factor: float, keep: bool,
            timeout: float) -> list[Path]:
    for w in preflight(sorted({f.parent for f in raw_files}), len(raw_files)):
        print(f"Note: {w}")

    jobs = []  # (raw file, disguised dng, output dir)
    for f in raw_files:
        try:
            raw = dng.read_raw(f)
            dng.placement_645d(raw)  # fails early if the sensor doesn't fit the 645D frame
        except dng.UnsupportedCamera as e:
            print(f"skipped {f.name}: {e}")
            continue
        except Exception as e:  # unreadable / corrupt file: skip it, keep going with the rest
            print(f"skipped {f.name}: cannot read it ({e})")
            continue
        work = f.parent / "_dxo_work"
        work.mkdir(exist_ok=True)
        # DxO picks its denoise strength from the ISO; old CCDs are noisier than a 645D at the same ISO
        dxo_iso = iso or round(raw.iso * iso_factor)
        src = dng.write_645d_dng(raw, work / f"{f.stem}_645D_iso{dxo_iso}.dng", dxo_iso)
        jobs.append((f, src, outdir or f.parent))
        print(f"prepared {src.name}  ({raw.camera.name}, ISO {raw.iso} -> {dxo_iso})")
    if not jobs:
        raise SystemExit("Nothing to process.")

    batch = jobs[0][1].parent / "pureraw_batch.txt"
    launch([src for _, src, _ in jobs], batch)
    print(f"\nDxO PureRAW is opening. Check the settings and click 'Start Processing'.\n"
          f"(Use DeepPRIME / DeepPRIME XD, output DNG, and switch the Optical Corrections off.)\n"
          f"Waiting for {len(jobs)} result(s)...")

    results, pending, sizes, warned = [], list(jobs), {}, False
    deadline = time.time() + timeout
    while pending and time.time() < deadline:
        time.sleep(3)
        for job in list(pending):
            source, src, out_dir = job
            found = find_output(src, output_dirs(src.parent))
            if found is None and not warned and non_dng_outputs(src, output_dirs(src.parent)):
                print("  WARNING: DxO is writing JPG/TIFF only. Tick 'DNG' as Output Format in DxO and process again.")
                warned = True
            if found is None or not _is_finished(found, sizes):
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            try:
                out, _ = restore.restore(found, source, out_dir / f"{source.stem}_denoised.dng")
            except PermissionError:
                continue  # DxO is still holding the file
            print(f"  done: {out}")
            results.append(out)
            pending.remove(job)
            if not keep:
                src.unlink(missing_ok=True)
                for extra in found.parent.glob(f"{src.stem}-dng_DxO_*"):
                    extra.unlink(missing_ok=True)
        if pending and not puraw_running():
            # PureRAW closed: give the last file a moment, then stop waiting
            deadline = min(deadline, time.time() + 10)

    for source, _, _ in pending:
        print(f"  no DxO result for {source.name} (cancelled or timed out)")
    if not keep:
        batch.unlink(missing_ok=True)
        for work in {src.parent for _, src, _ in jobs}:
            # only our own work folder and its DxO subfolder, and only if empty
            for d in [work / (_reg("destinationSubfolderName", "DxO") or "DxO"), work]:
                try:
                    d.rmdir()
                except OSError:
                    pass
    return results
