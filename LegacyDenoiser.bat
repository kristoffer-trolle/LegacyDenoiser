@echo off
setlocal
rem Legacy Denoiser: drag raw files (Kodak DCR, Mamiya MEF, Phase One IIQ) or folders onto this file
rem to denoise them with DxO PureRAW 3.
rem Strength: DxO sees each photo's own ISO times FACTOR (higher = stronger denoising).
set FACTOR=4
cd /d "%~dp0"

rem --- First run: make sure uv (runs the Python code) is installed ---
set "UV=%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe"
if exist "%UV%" goto have_uv
where uv >nul 2>nul
if not errorlevel 1 (
  set "UV=uv"
  goto have_uv
)
echo First run: installing uv, which this tool needs to run...
winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
if not exist "%UV%" (
  echo.
  echo Could not install uv automatically.
  echo Please install it from https://docs.astral.sh/uv/ and try again.
  pause
  exit /b 1
)
:have_uv

rem --- First run: download ExifTool (copies the photo metadata) ---
if not exist "tools\exiftool\exiftool.exe" (
  echo First run: downloading ExifTool...
  "%UV%" run legacy-denoiser setup
  if errorlevel 1 (
    pause
    exit /b 1
  )
)

if "%~1"=="" (
  echo.
  echo Drag raw files or folders onto LegacyDenoiser.bat to denoise them.
  echo.
  pause
  exit /b 0
)

"%UV%" run legacy-denoiser process %* --iso-factor %FACTOR%
pause
