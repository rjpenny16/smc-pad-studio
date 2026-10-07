$ErrorActionPreference = 'Stop'
$studioRoot = $PSScriptRoot
$versionLine = Select-String -Path (Join-Path $studioRoot 'controller.py') -Pattern "^VERSION\s*=\s*'(.+)'"
if (-not $versionLine) { throw 'VERSION was not found in controller.py' }
$version = $versionLine.Matches[0].Groups[1].Value
python -m pip install -r (Join-Path $studioRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
python -m PyInstaller --noconfirm --onefile --windowed --name "SMC-PAD-Studio-v$version" --icon "$studioRoot/studio.ico" --add-data "$studioRoot/ui;ui" --add-data "$studioRoot/studio.ico;." --collect-all imageio_ffmpeg --collect-data yt_dlp_ejs --distpath "$studioRoot/dist" --workpath "$studioRoot/build" --specpath $studioRoot "$studioRoot/main.py"
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed' }
