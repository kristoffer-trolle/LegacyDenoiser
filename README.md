# Legacy Denoiser

Modern AI noise reduction for raw files from **old digital cameras and backs** that today's denoise
programs don't support.

## 1. What it does

Programs like DxO PureRAW, Lightroom and Topaz can remove noise from raw files remarkably well, but only for
cameras they know. Raw files from older cameras, such as the Kodak DCS Pro Back 645 from 2002, are simply
refused.

Legacy Denoiser gets around that. It hands your raw files to **DxO PureRAW** in a form DxO accepts, lets DxO
remove the noise with its DeepPRIME AI, and then turns the result back into a normal raw file (DNG) from
your original camera:

```
4H9V1400.DCR   →   4H9V1400_denoised.dng   (saved in the same folder)
```

The denoised DNG:

- opens in Photoshop / Adobe Camera Raw, Lightroom and other raw editors, and you can still adjust white
  balance, exposure and everything else
- keeps the photo's original information (camera, exposure, date, ...)
- keeps the **edits you already made in Adobe Camera Raw** (crop, sliders, masks, camera profile), so you
  don't have to redo them

### Supported cameras

| Camera | Raw files |
|---|---|
| Kodak DCS Pro Back 645 | `.DCR` |
| Mamiya ZD | `.MEF` |
| Phase One P-series: P20, P21, P25, P30, P45 (also the + versions) | `.IIQ` |

### What you need

- A **Windows** PC
- **DxO PureRAW 3**, installed and activated. It's a paid program from DxO; this tool doesn't include it.
  Only version 3 has been tested.

## 2. How to use it

### Step 1: Install DxO PureRAW 3

Make sure DxO PureRAW 3 is installed and activated, and that you have started it at least once.

### Step 2: Download Legacy Denoiser

On the GitHub page, click the green **Code** button and either:

- choose **Download ZIP** and unpack it into a folder of your choice, or
- if you use git: `git clone https://github.com/kristoffer-trolle/LegacyDenoiser.git`

> If Windows shows "Windows protected your PC" the first time you run the tool, click **More info** and then
> **Run anyway**. You can avoid it by right-clicking the ZIP file, choosing **Properties**, ticking
> **Unblock** and clicking OK before you unpack it.

### Step 3: Start it with your raw files

**Close DxO PureRAW first** if it's open.

Then **drag your raw files, or a whole folder of them, onto `LegacyDenoiser.bat`** in the Legacy Denoiser
folder. A black window opens and shows what's happening.

The **first time**, the tool sets itself up. It installs a small helper program (uv), downloads the parts it
needs and downloads ExifTool. This takes a minute or two and only happens once.

> **Optional, for experienced users:** you can also run it from a terminal in the Legacy Denoiser folder,
> with extra options (see [Settings](#settings)):
> ```
> uv run legacy-denoiser process "D:\Photos\Kodak" --iso-factor 8
> ```

### Step 4: Click "Start Processing" in DxO

DxO PureRAW opens with a **"Process N photos with DxO PureRAW 3"** window. Before you click anything:

- Under **Output Format**, tick **DNG**. This is important: the tool can only work with DNG, not JPG or TIFF.
- Choose **DeepPRIME** or **DeepPRIME XD** (XD is slower but can recover a little more detail).
- Turning the **Optical Corrections** switches off is recommended. DxO doesn't know these old lenses anyway.

Then click **Start Processing**. DxO remembers these settings for next time.

### Step 5: Find your denoised files

When DxO is done, the black window finishes the job by itself. Your denoised photos are saved **next to the
originals**, with `_denoised` added to the name:

```
D:\Photos\Kodak\4H9V1400.DCR
D:\Photos\Kodak\4H9V1400_denoised.dng   ← new
```

Open them in Photoshop / Camera Raw or Lightroom like any other raw file. You can close the black window
when it says "Press any key to continue".

### Settings

**Strength.** DxO PureRAW 3 has no strength slider. The tool sets the strength through the ISO number it
tells DxO: by default the photo's own ISO × 4. To change it, open `LegacyDenoiser.bat` in Notepad and change
the line `set FACTOR=4`. Higher means stronger noise reduction (try 8 or 16 for very noisy photos, 2 for
gentler results).

**Terminal options** (`uv run legacy-denoiser process FILES [options]`):

| Option | Meaning |
|---|---|
| `--iso-factor N` | Strength: DxO sees the photo's ISO × N (default 4). |
| `--iso N` | Use a fixed ISO for DxO instead. |
| `-o FOLDER` | Save the results in another folder instead of next to the raw files. |
| `--keep` | Keep the temporary files (the disguised DNG and DxO's own output). |
| `--timeout S` | Maximum seconds to wait for DxO (default 3600). |

### Your Adobe Camera Raw edits

Adobe Camera Raw saves your edits of a raw file in a small file next to it with the same name, for example
`4H9V1400.xmp`. If that file exists, all your edits are copied into the denoised DNG automatically.

- **Noise reduction** in your edits is set to 0, because the photo is already denoised. You may also want to
  lower **Sharpening** a bit, since DxO sharpens slightly too.
- Custom **camera profiles** you use still show up for the denoised DNG.
- Edits made in **Camera Raw 14 or newer** (the new masking tools) need Camera Raw 14 or newer to open
  correctly.
- If you edit in **Lightroom**, your edits live in the Lightroom catalog. Select the photos and press
  **Ctrl+S** ("Save Metadata to File") first, so the `.xmp` files are created.

### Good to know

- **DxO must be closed** when you start. If it's open, the tool asks you to close it.
- Allow about **350 MB of free disk space per photo** while it works. The finished DNGs are about
  100–130 MB each.
- If you process the same photo again, the old `_denoised.dng` is **overwritten**.
- Files from unsupported cameras, or damaged files, are skipped with a message, and the rest carry on.
- If DxO only produces JPG or TIFF files, the window tells you to tick DNG and try again.

## 3. How it works

DxO PureRAW only processes cameras it has calibrated, and these old cameras aren't among them. Its supported
cameras do include the **Pentax 645D**, a medium-format camera with a Kodak CCD sensor, which saves its raw
files as DNG and has a large 7264×5440 sensor. So the tool disguises each photo as a 645D:

1. **Disguise.** The original sensor data is read with [LibRaw](https://www.libraw.org/) and placed in the
   middle of a 645D-sized frame, lined up so the colour filter pattern matches. The rest of the frame is
   filled with a mirror image of the photo, so the denoiser sees natural edges, and the file is labelled as
   a 645D DNG. DxO's program files are not modified.
2. **Denoise.** DxO PureRAW is started with the files already loaded, through the same hidden option its
   Lightroom plugin uses.
3. **Restore.** The photo is cut back out of DxO's result. The tool measures the colour change DxO applied by
   comparing against the original raw file and undoes it. It then writes a DNG with the original camera's
   identity (using Adobe's own name for the camera, so profiles match), orientation, metadata and Camera
   Raw edits.

**Why the ISO trick:** DxO picks its noise reduction strength from the camera model and the ISO. Old CCD
sensors are noisier than a 645D at the same ISO, so the tool reports a higher ISO to DxO. The finished DNG
gets the real ISO back.

### Limitations

- **One click remains.** PureRAW has no official command-line mode, so you still click "Start Processing".
  A DxO update could change the hidden option the tool relies on.
- **The result is a "linear" DNG.** DxO has already demosaiced the image, just like DxO's own and Lightroom's
  Denoise output. Everything stays editable, but it isn't the untouched sensor data any more.
- **The files are uncompressed** and therefore large.
- **Very clean photos gain little.** A Mamiya ZD or Phase One photo at ISO 50 is already almost noise-free.
- **Phase One P40+, P65+ and the IQ series are not supported.** Their sensors are larger than the Pentax 645D
  the tool disguises photos as. Their files use the same `.IIQ` extension and are skipped with a message.
- **Only the Phase One P25+ has been tested** with a real file. The other P-series backs use the same file
  format and are handled the same way, but haven't been tried.

## 4. For developers

Requires [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv`). uv installs Python and the
libraries by itself.

```
uv run legacy-denoiser setup                # download ExifTool into tools/exiftool (not stored in git)
uv run legacy-denoiser check                # check DxO PureRAW, its camera list and ExifTool
uv run legacy-denoiser process FILES        # the full workflow (what LegacyDenoiser.bat runs)
uv run legacy-denoiser todng FILES          # plain DNG, pixel-identical, no denoising (edits included)
uv run legacy-denoiser dxo FILES --iso 100 400 1600   # only create disguised 645D DNGs
uv run legacy-denoiser restore DXO_FILES    # only restore DxO output DNGs
```

### Adding a camera

Everything except the camera's identity is generic. A camera can be added if:

1. LibRaw can read its raw files.
2. It uses a normal 2×2 Bayer colour filter (not Fujifilm X-Trans, Sigma Foveon or similar).
3. Its sensor data fits inside the 645D frame (7264×5440 pixels, in the orientation the DNG stores it).

Then add an entry to `CAMERAS` in `src/legacy_denoiser/cameras.py` and the file extension to `.gitignore`:

```python
Camera(
    name="Mamiya ZD",                 # shown in messages
    extensions=(".mef",),             # raw file extensions
    exif_model="MAMIYA ZD",           # the Model tag in the raw file (exiftool -Model FILE)
    make="Mamiya-OP Co.,Ltd.",        # Make/Model written to the DNG (copy from the raw file)
    model="MAMIYA ZD",
    unique_model="Mamiya ZD",         # Adobe Camera Raw's name for the camera
    iso_tag="ISO",                    # tag holding the ISO (the Kodak uses ExposureIndex)
),
```

**Orientation.** Some raw formats store the pixels on their side. Check how Camera Raw treats them: look at
`tiff:Orientation` in a `.xmp` sidecar Camera Raw made for a photo that displays correctly.

- If it is `6` or `8` (like the Mamiya ZD), Camera Raw keeps the pixels as stored and rotates on display.
  Nothing to do; the DNG does the same.
- If it is `1` although the photo needs turning (like Phase One backs), Camera Raw rotates the pixels itself
  and your edits refer to the turned image. Add `bake_orientation=True`; the DNG then stores turned pixels.

**Maker calibration.** Some formats (Phase One) store raw data that still needs the maker's calibration,
such as a black level per row and column. LibRaw only applies it while processing. If a plain DNG
(`todng`) shows a strong colour cast that white balance can't fix, add `libraw_corrections=True`.

**Camera families.** `exif_model` is a regular expression, and `{model}` in `name`, `model` and
`unique_model` is replaced by the file's own model, so one entry can cover a whole family (see the Phase One
entry).

Adobe's camera name matters: Camera Raw only applies Adobe Standard and camera-specific `.dcp` profiles when
the DNG's `UniqueCameraModel` matches it exactly. It can be found in the camera's `.dcp` profile files or in
a DNG made with Adobe DNG Converter.

### Project layout

```
src/legacy_denoiser/
  __init__.py   command line
  cameras.py    supported cameras: recognition and identity
  dng.py        reading raw files (LibRaw), writing DNGs, the 645D disguise, metadata and edit transfer
  dxo.py        launching DxO PureRAW, pre-flight checks, waiting for results
  restore.py    cropping, colour calibration and original identity for DxO output
LegacyDenoiser.bat  drag-and-drop launcher with automatic first-run setup
```
