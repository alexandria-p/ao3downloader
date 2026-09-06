<#
.SYNOPSIS
    Runs the ao3downloader console menu from this working copy, not the PyPI release.

.DESCRIPTION
    site/public/install/ao3downloader-windows.ps1 installs ao3downloader from PyPI, so it
    always runs the last released version. This script runs the code in this folder as-is -
    the package is installed into the project's .venv in editable mode, so source edits take
    effect the next time you run it with no reinstall step.

    ao3downloader resolves settings.ini, data.json, logs/ and a relative DownloadFolder
    against the working directory, so this always runs from the root of this working copy and
    uses the config sitting next to it, creating it if missing. Letting the shell's own
    directory decide - normally your home folder - quietly creates a second settings.ini and
    data.json there and reads those instead, which looks like saved settings being ignored.

    Where fics are saved is controlled by the DownloadFolder setting inside settings.ini.

    For the web ui and its download buttons, use run-gui.ps1 instead.

.PARAMETER Sync
    Reinstall dependencies before running. Needed after editing pyproject.toml or pulling
    changes that add a dependency. Otherwise the existing .venv is used with no network call.

.PARAMETER SystemCerts
    Tell uv to use the Windows certificate store. Needed on networks that intercept TLS,
    where uv otherwise fails with "invalid peer certificate: UnknownIssuer".

.PARAMETER NoPause
    Don't wait for a keypress at the end. Use when running from an existing terminal.

.EXAMPLE
    .\run-local.ps1

.EXAMPLE
    .\run-local.ps1 -Sync -SystemCerts
    Reinstalls dependencies first, using the Windows certificate store.
#>

[CmdletBinding()]
param(
    [switch] $Sync,
    [switch] $SystemCerts,
    [switch] $NoPause
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'ao3-env.ps1')

$exitCode = 0

try {
    $projectRoot = Get-Ao3Root -ScriptRoot $PSScriptRoot
    if (-not $projectRoot) { exit 1 }
    if (-not (Test-Ao3Uv)) { exit 1 }

    Initialize-Ao3Config -Root $projectRoot

    $alreadyInstalled = Test-Path (Join-Path $projectRoot '.venv')
    if (-not (Invoke-Ao3Sync -Root $projectRoot -Force:$Sync -SystemCerts:$SystemCerts)) { exit 1 }

    Write-Host ''

    $runArgs = @('run', '--project', $projectRoot)
    if ($alreadyInstalled -and -not $Sync) { $runArgs += '--no-sync' }
    $runArgs += 'ao3downloader'

    Push-Location $projectRoot
    try {
        & uv @runArgs
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if ($exitCode -ne 0) {
        Write-Problem "ao3downloader exited with code $exitCode"
    }
}
catch {
    Write-Problem 'an unexpected error occurred'
    Write-Problem $_
    $exitCode = 1
}

if (-not $NoPause) {
    Read-Host 'press enter to exit'
}

exit $exitCode
