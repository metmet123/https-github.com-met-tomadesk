param(
    [switch]$Clean,
    [switch]$KeepWorkFiles,
    [string]$PythonExecutable = 'python'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = $PSScriptRoot
$ReleaseRoot = Join-Path $ProjectRoot 'release'
$WorkRoot = Join-Path $ProjectRoot '.package-build'
$SpecFile = Join-Path $ProjectRoot 'shortcut_launcher.spec'
$StagingExecutable = Join-Path $ReleaseRoot 'toma_shortcut_program.exe'
$Executable = Join-Path $ReleaseRoot 'TomaDesk.exe'

function Remove-PackageWork {
    $resolved = [System.IO.Path]::GetFullPath($WorkRoot)
    $expected = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot '.package-build'))
    if ($resolved -ne $expected) { throw 'Unexpected build cleanup path.' }
    if (Test-Path -LiteralPath $resolved) {
        if ((Get-Item -LiteralPath $resolved -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Build work directory must not be a junction or symlink.'
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

if ($Clean) {
    Remove-PackageWork
}

$BuildPython = (Get-Command $PythonExecutable -ErrorAction Stop).Source
$PythonBase = & $BuildPython -c 'import sys; print(sys.base_prefix)'
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve build Python.' }
$PreviousPath = $env:PATH
try {
    # Dependency discovery must not pick up unrelated DLLs from tools on PATH
    # (for example Poppler ICU or an older libheif Universal CRT).
    $env:PATH = (@((Split-Path $BuildPython), $PythonBase,
        (Join-Path $PythonBase 'DLLs'), (Join-Path $env:SystemRoot 'System32'),
        $env:SystemRoot) | Select-Object -Unique) -join ';'
    & $BuildPython -m PyInstaller --noconfirm --clean `
        --distpath $ReleaseRoot `
        --workpath $WorkRoot `
        $SpecFile
    $BuildExitCode = $LASTEXITCODE
} finally {
    $env:PATH = $PreviousPath
}

if ($BuildExitCode -ne 0) {
    throw "PyInstaller failed with exit code $BuildExitCode. Existing release was not replaced."
}

if (-not (Test-Path -LiteralPath $StagingExecutable)) {
    throw "Build finished without the expected staging executable: $StagingExecutable"
}
Move-Item -LiteralPath $StagingExecutable -Destination $Executable -Force

if (-not (Test-Path -LiteralPath $Executable)) {
    throw "Build finished without the expected executable: $Executable"
}

if (-not $KeepWorkFiles -and (Test-Path -LiteralPath $WorkRoot)) {
    Remove-PackageWork
}

Write-Host "Standalone package: $Executable"
Write-Host "Distribute this single EXE file."
