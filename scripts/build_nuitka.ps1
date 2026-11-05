# Build 2Wings standalone with Nuitka.
$ErrorActionPreference = "Stop"

$Repo = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

$DistRoot = Join-Path $Repo "dist"
$OutDir = Join-Path $DistRoot "2Wings"
$VersionFile = Join-Path $Repo "src\core\version.py"
$Version = "1.0.0.0"
if (Test-Path $VersionFile) {
    $match = Select-String -Path $VersionFile -Pattern '__version__\s*=\s*"([^"]+)"'
    if ($match) {
        $Version = (($match.Matches[0].Groups[1].Value -replace "-.*$", "") + ".0")
    }
}

$icon = Join-Path $Repo "assets\icons\app.ico"
if (-not (Test-Path $icon)) {
    Write-Host "Generating icon assets..."
    Push-Location (Join-Path $Repo "tools")
    npm install --silent 2>$null
    node generate_icons.mjs
    Pop-Location
}

# The full PySide6 package would drag WebEngine into the build: see requirements-ui.txt.
& $Py -c "import importlib.util, sys; sys.exit(1 if importlib.util.find_spec('PySide6.QtWebEngineCore') else 0)"
if ($LASTEXITCODE -ne 0) {
    throw "Full PySide6 is installed. Keep only PySide6-Essentials: docs\BUILD.md."
}

Write-Host "Building 2Wings $Version with Nuitka..."
if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null

$buildArgs = @(
    "-m", "nuitka",
    "--standalone",
    "--mingw64",
    "--assume-yes-for-downloads",
    "--enable-plugin=pyside6",
    "--noinclude-qt-translations",
    "--output-dir=$DistRoot",
    "--output-filename=2Wings.exe",
    "--windows-icon-from-ico=$icon",
    "--windows-console-mode=disable",
    "--windows-uac-admin",
    "--product-name=2Wings",
    "--file-version=$Version",
    "--company-name=2Wings",
    "--include-data-dir=$(Join-Path $Repo 'assets\icons')=assets/icons",
    "--include-data-dir=$(Join-Path $Repo 'assets\hosts')=assets/hosts",
    "--include-data-dir=$(Join-Path $Repo 'assets\lua')=assets/lua",
    "--include-package=src",
    "--include-package=qfluentwidgets",
    "--include-package-data=qfluentwidgets",
    "--include-package=qframelesswindow",
    "--include-package=httpx",
    "--include-package=httpcore",
    "--include-package=anyio",
    "--include-package=h11",
    "--include-package=certifi",
    "--include-package=idna",
    "--include-package=PIL",
    "--include-package=pystray",
    "--include-package=cryptography",
    "--include-package=h2",
    "--include-package=hpack",
    "--include-package=hyperframe",
    "--nofollow-import-to=tkinter",
    "--nofollow-import-to=unittest",
    "--nofollow-import-to=test",
    "--nofollow-import-to=pytest",
    "--nofollow-import-to=mcp",
    (Join-Path $Repo "run.py")
)

& $Py @buildArgs
if ($LASTEXITCODE -ne 0) { throw "Nuitka build failed with exit code $LASTEXITCODE" }

$builtDir = Join-Path $DistRoot "run.dist"
if (-not (Test-Path $builtDir)) {
    $builtDir = Get-ChildItem $DistRoot -Directory | Where-Object { $_.Name -like "*.dist" } | Select-Object -First 1
    if ($builtDir) { $builtDir = $builtDir.FullName }
}
if (-not (Test-Path $builtDir)) { throw "Nuitka output directory not found in dist/" }

if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
Rename-Item $builtDir $OutDir

$exe = Join-Path $OutDir "2Wings.exe"
if (-not (Test-Path $exe)) {
    $legacy = Join-Path $OutDir "run.exe"
    if (Test-Path $legacy) { Rename-Item $legacy "2Wings.exe" }
}

foreach ($intermediate in @("run.build", "run.onefile-build")) {
    $path = Join-Path $DistRoot $intermediate
    if (Test-Path $path) {
        Remove-Item -Recurse -Force $path
    }
}

$UpdaterSource = Join-Path $Repo "scripts\release_assets\TwoWingsUpdate"
if (-not (Test-Path (Join-Path $UpdaterSource "TwoWingsUpdate.exe"))) {
    Write-Host "TwoWingsUpdate is not built yet, building..."
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_update_splash.ps1")
    if ($LASTEXITCODE -ne 0) { throw "TwoWingsUpdate build failed with exit code $LASTEXITCODE" }
}
$UpdaterDest = Join-Path $OutDir "updater"
if (Test-Path $UpdaterDest) { Remove-Item -Recurse -Force $UpdaterDest }
Copy-Item -Path $UpdaterSource -Destination $UpdaterDest -Recurse -Force

Write-Host ""
Write-Host "Build complete: $OutDir"
Write-Host "  2Wings.exe"
Write-Host "  updater\TwoWingsUpdate.exe (from scripts\release_assets\TwoWingsUpdate\)"
