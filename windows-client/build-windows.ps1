$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $env:PYTHONNOUSERSITE = '1'
    & '.\.venv\Scripts\python.exe' -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
    & '.\.venv\Scripts\python.exe' tools\verify_independence.py
    if ($LASTEXITCODE -ne 0) { throw 'Independence check failed.' }
    $taskVersion = & '.\.venv\Scripts\python.exe' tools\write_version_info.py --output build\version-info.txt
    if ($LASTEXITCODE -ne 0) { throw 'Version metadata generation failed.' }
    & '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --clean --onedir --windowed --noupx --paths . --add-data "$PSScriptRoot\web;web" --add-data "$PSScriptRoot\assets;assets" --collect-all webview --collect-all pythonnet --collect-all clr_loader --hidden-import webview.platforms.winforms --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module cefpython3 --icon "$PSScriptRoot\assets\FinfusionClient.ico" --version-file "$PSScriptRoot\build\version-info.txt" --name FinfusionClient --distpath dist --workpath build\pyinstaller --specpath build tools\windows_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    Copy-Item -LiteralPath README.md -Destination 'dist\FinfusionClient\README.md'
    Copy-Item -LiteralPath docs\ACCEPTANCE-1.0.md -Destination 'dist\FinfusionClient\ACCEPTANCE.md'
    Copy-Item -LiteralPath docs\MARKET.md -Destination 'dist\FinfusionClient\MARKET.md'
    Copy-Item -LiteralPath docs\INTEGRATION-2026-10-09.md -Destination 'dist\FinfusionClient\INTEGRATION-2026-10-09.md'
    Copy-Item -LiteralPath docs\DEPENDENCIES.json -Destination 'dist\FinfusionClient\DEPENDENCIES.json'
    if (Test-Path -LiteralPath LICENSES) { Copy-Item -LiteralPath LICENSES -Destination 'dist\FinfusionClient' -Recurse -Force }
    Copy-Item -LiteralPath docs\UI-Reference.md -Destination 'dist\FinfusionClient\UI-Reference.md'
    Copy-Item -LiteralPath docs\DELIVERY-1.0.md -Destination 'dist\FinfusionClient\DELIVERY.md'
    Compress-Archive -Path 'dist\FinfusionClient' -DestinationPath "dist\FinfusionClient-$taskVersion-windows-x64.zip" -Force
    Write-Output 'Unsigned build: dist\FinfusionClient\FinfusionClient.exe'
} finally { Pop-Location }
