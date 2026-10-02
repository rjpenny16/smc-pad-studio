$ErrorActionPreference = 'Stop'
$studioRoot = $PSScriptRoot
python -m pip install -r (Join-Path $studioRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
python -m PyInstaller --noconfirm --onefile --windowed --name SMC-PAD-Studio-v0.6.0 --icon "$studioRoot/studio.ico" --add-data "$studioRoot/studio.html;." --add-data "$studioRoot/studio.ico;." --distpath "$studioRoot/dist" --workpath "$studioRoot/build" --specpath $studioRoot "$studioRoot/main.py"
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed' }
