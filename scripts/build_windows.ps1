param([string]$Python = (Join-Path $PSScriptRoot '..\.venv-dev\Scripts\python.exe'))
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $taskRoot
try {
    & $Python -m unittest discover -s tests -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed; package not built.' }
    & $Python -m PyInstaller --noconfirm --clean --onedir --name LANObserver --add-data 'lan_observer/templates;lan_observer/templates' --add-data 'lan_observer/static;lan_observer/static' app.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    Copy-Item -LiteralPath README.md -Destination dist\LANObserver\README.md
    foreach ($doc in @('AUDIT.md', 'BUG_LOG.md', 'OVERHAUL_PLAN.md', 'IMPLEMENTATION_STATUS.md', 'VISUAL_AUDIT.md')) {
        Copy-Item -LiteralPath $doc -Destination (Join-Path 'dist\LANObserver' $doc)
    }
    New-Item -ItemType Directory -Path dist\LANObserver\screenshots -Force | Out-Null
    Copy-Item -LiteralPath screenshots\inventory-v0.2.png -Destination dist\LANObserver\screenshots\inventory-v0.2.png
    Copy-Item -LiteralPath screenshots\inventory-mobile-v0.2.png -Destination dist\LANObserver\screenshots\inventory-mobile-v0.2.png
    Copy-Item -LiteralPath screenshots\inventory-swiss-v0.3-desktop.png -Destination dist\LANObserver\screenshots\inventory-swiss-v0.3-desktop.png
    Copy-Item -LiteralPath screenshots\inventory-swiss-v0.3-mobile.png -Destination dist\LANObserver\screenshots\inventory-swiss-v0.3-mobile.png
    Copy-Item -LiteralPath audit -Destination dist\LANObserver\audit -Recurse -Force
    & $Python scripts\smoke_package.py
    if ($LASTEXITCODE -ne 0) { throw 'Packaged application smoke test failed.' }
    Copy-Item -LiteralPath audit\overhaul-package-checks.json -Destination dist\LANObserver\audit\overhaul-package-checks.json
    Compress-Archive -Path dist\LANObserver -DestinationPath dist\LANObserver-0.2.0-windows-x64.zip -Force
    Get-FileHash -LiteralPath dist\LANObserver-0.2.0-windows-x64.zip -Algorithm SHA256 | Select-Object Hash,Path
} finally { Pop-Location }
