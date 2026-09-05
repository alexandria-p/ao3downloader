<#
.SYNOPSIS
    Runs ao3downloader from this working copy instead of the published PyPI release.

.DESCRIPTION
    site/public/install/ao3downloader-windows.ps1 installs ao3downloader from PyPI, so it
    always runs the last released version. This script runs the code in this folder as-is,
    which is what you want while you are working on it - the package is installed into the
    project's .venv in editable mode, so source edits take effect the next time you run it
    with no reinstall step.

    ao3downloader resolves settings.ini, data.json, logs/ and a relative DownloadFolder
    against the working directory. This script therefore always runs from its own folder
    and uses the settings.ini and data.json sitting next to it, creating them if they are
    missing. Letting the shell's own directory decide - normally your home folder - quietly
    creates a second settings.ini and data.json there and reads those instead, which looks
    like saved settings being ignored.

    Where fics are saved is controlled by the DownloadFolder setting inside settings.ini,
    not by this script.

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

function Write-Step($message) {
    Write-Host $message -ForegroundColor Cyan
}

function Write-Problem($message) {
    Write-Host $message -ForegroundColor Yellow
}

try {
    $projectRoot = $PSScriptRoot
    if (-not $projectRoot) { $projectRoot = (Get-Location).Path }

    if (-not (Test-Path (Join-Path $projectRoot 'pyproject.toml'))) {
        Write-Problem "no pyproject.toml in $projectRoot"
        Write-Problem 'this script has to stay in the root of the ao3downloader working copy.'
        exit 1
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        # the .local\bin case: uv is installed but this session started before it was on PATH
        $uvPath = Join-Path $env:USERPROFILE '.local\bin'
        if (Test-Path (Join-Path $uvPath 'uv.exe')) {
            $env:PATH = "$uvPath;$env:PATH"
        }
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Problem 'uv is required but was not found.'
        Write-Problem 'install it with:'
        Write-Host '    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
        Write-Problem 'then open a new terminal and run this script again.'
        exit 1
    }

    # the config this run will use, always the pair next to this script
    $settingsFile = Join-Path $projectRoot 'settings.ini'
    $dataFile = Join-Path $projectRoot 'data.json'

    if (Test-Path $settingsFile) {
        Write-Step "settings.ini: $settingsFile"
    }
    else {
        $template = Join-Path $projectRoot 'ao3downloader\settings\settings.ini'
        if (Test-Path $template) {
            Copy-Item -Path $template -Destination $settingsFile
            Write-Step "settings.ini: created $settingsFile"
        }
        else {
            # no template in the working copy; ao3downloader writes one from the package
            Write-Step 'settings.ini: missing, ao3downloader will create it'
        }
    }

    if (Test-Path $dataFile) {
        Write-Step "data.json:    $dataFile"
    }
    else {
        # no BOM - python's json reader chokes on one
        [System.IO.File]::WriteAllText($dataFile, '{}', (New-Object System.Text.UTF8Encoding $false))
        Write-Step "data.json:    created $dataFile"
    }

    # show where fics will land, since that is the other thing settings.ini decides
    if (Test-Path $settingsFile) {
        $downloadFolder = (Select-String -Path $settingsFile -Pattern '^\s*DownloadFolder\s*=\s*(.*)$' |
            Select-Object -First 1).Matches.Groups[1].Value
        if ($downloadFolder) {
            Write-Step "downloads:    $($downloadFolder.Trim()) (set in settings.ini)"
        }
    }

    $needsSync = $Sync -or -not (Test-Path (Join-Path $projectRoot '.venv'))

    if ($needsSync) {
        Write-Step 'installing dependencies...'
        $syncArgs = @('sync', '--project', $projectRoot, '--python', '3.12')
        if ($SystemCerts) { $syncArgs += '--system-certs' }

        & uv @syncArgs
        if ($LASTEXITCODE -ne 0) {
            if ($SystemCerts) {
                Write-Problem 'could not install dependencies.'
                exit 1
            }
            # the usual cause is a network that intercepts TLS, so retry against the
            # Windows certificate store before giving up
            Write-Problem 'dependency install failed. retrying with the Windows certificate store...'
            & uv @syncArgs --system-certs
            if ($LASTEXITCODE -ne 0) {
                Write-Problem 'could not install dependencies.'
                exit 1
            }
        }
    }

    Write-Host ''

    $runArgs = @('run', '--project', $projectRoot)
    if (-not $needsSync) { $runArgs += '--no-sync' }
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
