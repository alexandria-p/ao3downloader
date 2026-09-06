<#
.SYNOPSIS
    Produces the deployable bundle in build/.

.DESCRIPTION
    Compiles the web app, generates a self-contained launcher from powershell_source/, and
    gathers everything needed to run the site into build/. See INSTRUCTIONS.txt.

    The real work is in powershell_source/build_artifacts.py; this is just the entry point.

.PARAMETER SkipWeb
    Reuse the web/ folder already in build/ instead of recompiling it. Useful when only the
    launcher or the python package has changed.

.EXAMPLE
    .\generate_build_artifacts.ps1
#>

[CmdletBinding()]
param(
    [switch] $SkipWeb
)

$ErrorActionPreference = 'Stop'

try {
    $pythonHome = Join-Path $PSScriptRoot 'powershell_source\ao3_download_helper'
    if (-not (Test-Path (Join-Path $pythonHome 'pyproject.toml'))) {
        Write-Host "no pyproject.toml under $pythonHome" -ForegroundColor Yellow
        Write-Host 'this script has to stay in the repository root.' -ForegroundColor Yellow
        exit 1
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        $uvPath = Join-Path $env:USERPROFILE '.local\bin'
        if (Test-Path (Join-Path $uvPath 'uv.exe')) { $env:PATH = "$uvPath;$env:PATH" }
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host 'uv is required but was not found.' -ForegroundColor Yellow
        Write-Host '    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
        exit 1
    }

    # pyproject.toml lives with the python code, so uv has to be pointed at it
    $buildArgs = @('run', '--project', $pythonHome, '--no-sync', 'python',
                   'powershell_source/ao3_download_helper/build_artifacts.py')
    if ($SkipWeb) { $buildArgs += '--skip-web' }

    Push-Location $PSScriptRoot
    try {
        & uv @buildArgs
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if ($exitCode -ne 0) {
        Write-Host "the build failed (exit code $exitCode)" -ForegroundColor Yellow
    }
    exit $exitCode
}
catch {
    Write-Host 'an unexpected error occurred' -ForegroundColor Yellow
    Write-Host $_ -ForegroundColor Yellow
    exit 1
}
