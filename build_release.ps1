param(
    [switch]$Clean,
    [switch]$KeepWorkFiles
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = $PSScriptRoot
$ReleaseRoot = Join-Path $ProjectRoot 'release'
$WorkRoot = Join-Path $ProjectRoot '.package-build'
$SpecFile = Join-Path $ProjectRoot 'shortcut_launcher.spec'
$StagingExecutable = Join-Path $ReleaseRoot 'toma_shortcut_program.exe'
$Executable = Join-Path $ReleaseRoot 'TomaDesk.exe'

if ($Clean) {
    if (Test-Path -LiteralPath $WorkRoot) {
        Remove-Item -LiteralPath $WorkRoot -Recurse -Force
    }
    foreach ($target in @($StagingExecutable, $Executable)) {
        if (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Force
        }
    }
}

python -m PyInstaller --noconfirm --clean `
    --distpath $ReleaseRoot `
    --workpath $WorkRoot `
    $SpecFile

if (-not (Test-Path -LiteralPath $StagingExecutable)) {
    throw "Build finished without the expected staging executable: $StagingExecutable"
}
Move-Item -LiteralPath $StagingExecutable -Destination $Executable -Force

if (-not (Test-Path -LiteralPath $Executable)) {
    throw "Build finished without the expected executable: $Executable"
}

if (-not $KeepWorkFiles -and (Test-Path -LiteralPath $WorkRoot)) {
    Remove-Item -LiteralPath $WorkRoot -Recurse -Force
}

Write-Host "Standalone package: $Executable"
Write-Host "Distribute this single EXE file."