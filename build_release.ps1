# build_release.ps1 — Build portable release package
$ErrorActionPreference = "Stop"

$AppName = "Advanced-Network-Tool"
$Version = "1.0"
$ReleaseName = "$AppName-v$Version-Portable"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Building $ReleaseName" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Clean previous builds
Write-Host "`n[1/5] Cleaning previous builds..." -ForegroundColor Yellow
if (Test-Path .\build) { Remove-Item -Recurse -Force .\build }
if (Test-Path .\dist) { Remove-Item -Recurse -Force .\dist }
if (Test-Path .\release) { Remove-Item -Recurse -Force .\release }

# Build with PyInstaller
Write-Host "[2/5] Building with PyInstaller..." -ForegroundColor Yellow
python -m PyInstaller --noconfirm --clean "ANT.spec"
if ($LASTEXITCODE -ne 0) {
    Write-Host "BUILD FAILED" -ForegroundColor Red
    exit 1
}

# Create release folder
Write-Host "[3/5] Creating release folder..." -ForegroundColor Yellow
$releaseDir = ".\release\$ReleaseName"
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null

# Copy build output
Copy-Item -Path ".\dist\AdvancedNetworkTool\*" -Destination $releaseDir -Recurse -Force

# Copy README
if (Test-Path .\README.txt) {
    Copy-Item .\README.txt $releaseDir
}

# Create zip
Write-Host "[4/5] Creating zip archive..." -ForegroundColor Yellow
$zipPath = ".\release\$ReleaseName.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path $releaseDir -DestinationPath $zipPath -CompressionLevel Optimal

# Summary
$exeSize = (Get-Item "$releaseDir\AdvancedNetworkTool.exe").Length / 1MB
$zipSize = (Get-Item $zipPath).Length / 1MB
$fileCount = (Get-ChildItem $releaseDir -Recurse -File).Count

Write-Host "`n[5/5] Build complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Release: $ReleaseName"
Write-Host "  Folder:  release\$ReleaseName\"
Write-Host "  Zip:     release\$ReleaseName.zip"
Write-Host "  Files:   $fileCount"
Write-Host "  EXE:     $([math]::Round($exeSize, 1)) MB"
Write-Host "  ZIP:     $([math]::Round($zipSize, 1)) MB"
Write-Host "========================================" -ForegroundColor Cyan

# Refresh icon cache
ie4uinit.exe -show

Write-Host "`nDone. Test by unzipping on a machine with no Python installed." -ForegroundColor Green
