<#
.SYNOPSIS
    Starts everything the web ui needs: the local helper and the Angular dev server.

.DESCRIPTION
    The page at http://localhost:4200 can browse your downloaded bookmarks on its own, but
    the two download buttons need the local helper (ao3downloader.server) running, because a
    browser cannot reach ao3, cannot hold an ao3 login, and cannot read the ebook files the
    update scan looks at.

    This starts the helper in its own window, then runs the dev server here. Closing this
    window stops the dev server; the helper window can be closed separately.

    Like run-local.ps1, everything runs from the root of this working copy, so the
    settings.ini and data.json next to this script are the ones that get used.

.PARAMETER Sync
    Reinstall python dependencies before starting.

.PARAMETER SystemCerts
    Tell uv to use the Windows certificate store, for networks that intercept TLS.

.PARAMETER Port
    Port for the Angular dev server. Defaults to 4200.

.EXAMPLE
    .\run-gui.ps1
#>

[CmdletBinding()]
param(
    [switch] $Sync,
    [switch] $SystemCerts,
    [int] $Port = 4200
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'ao3-env.ps1')

$helper = $null

try {
    $projectRoot = Get-Ao3Root -ScriptRoot $PSScriptRoot
    if (-not $projectRoot) { exit 1 }
    if (-not (Test-Ao3Uv)) { exit 1 }

    Initialize-Ao3Config -Root $projectRoot
    if (-not (Invoke-Ao3Sync -Root $projectRoot -Force:$Sync -SystemCerts:$SystemCerts)) { exit 1 }

    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Problem 'npm was not found. install node.js, then run this again.'
        exit 1
    }

    if (-not (Test-Path (Join-Path $projectRoot 'GUI\node_modules'))) {
        Write-Step 'installing web dependencies (first run only)...'
        & npm --prefix (Join-Path $projectRoot 'GUI') install
        if ($LASTEXITCODE -ne 0) {
            Write-Problem 'could not install web dependencies.'
            exit 1
        }
    }

    Write-Host ''
    Write-Step 'starting the local helper in a separate window...'
    # its own window so its output stays readable next to the dev server's
    # no --project here: Start-Process joins ArgumentList without quoting, so a path
    # containing spaces would be split. -WorkingDirectory already puts uv in the project.
    $helper = Start-Process -PassThru -WorkingDirectory $projectRoot -FilePath 'uv' `
        -ArgumentList @('run', '--no-sync', 'python', '-m', 'ao3downloader.server')

    Start-Sleep -Seconds 2
    if ($helper.HasExited) {
        Write-Problem 'the local helper stopped immediately. the download buttons will not work.'
        Write-Problem 'try running it on its own to see why:'
        Write-Host '    uv run python -m ao3downloader.server'
    }
    else {
        Write-Step "local helper running (pid $($helper.Id))"
    }

    Write-Host ''
    Write-Step "starting the web ui on http://localhost:$Port"
    Write-Step 'press ctrl+c to stop.'
    Write-Host ''

    & npm --prefix (Join-Path $projectRoot 'GUI') start -- --port $Port
}
catch {
    Write-Problem 'an unexpected error occurred'
    Write-Problem $_
}
finally {
    if ($helper -and -not $helper.HasExited) {
        Write-Host ''
        Write-Step 'stopping the local helper...'
        Stop-Process -Id $helper.Id -Force -ErrorAction SilentlyContinue
    }
}
