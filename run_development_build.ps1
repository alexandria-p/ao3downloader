<#
.SYNOPSIS
    Starts everything the web ui needs: the local helper and the web server.

.DESCRIPTION
    The page can browse bookmarks you have already downloaded on its own, but the two
    download buttons need the local helper running, because a browser cannot reach ao3,
    cannot hold an ao3 login, and cannot read the ebook files the update scan looks at.

    This script works in two places, and picks the right one automatically:

      - in the working copy, it runs the Angular dev server against gui_source/
      - in a generated build (a folder containing web/), it serves those prebuilt files

    Everything runs from the python project folder, so the settings.ini, data.json and
    logs/ there are the ones that get used. Where fics are saved is the DownloadFolder
    setting inside settings.ini.

.PARAMETER Sync
    Reinstall python dependencies before starting.

.PARAMETER SystemCerts
    Tell uv to use the Windows certificate store, for networks that intercept TLS.

.PARAMETER Port
    Port for the web ui. Defaults to 4200.

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

# shared functions live with the python project. a generated build has them pasted in
# place of these two lines instead, so the shipped copy has nothing to dot-source.
$envScript = Join-Path $PSScriptRoot 'powershell_source\ao3_download_helper\ao3-env.ps1'
. $envScript

$helper = $null

try {
    $projectRoot = Get-Ao3Root -ScriptRoot $PSScriptRoot
    if (-not $projectRoot) { exit 1 }
    if (-not (Test-Ao3Uv)) { exit 1 }

    # settings.ini, data.json and logs\ sit above the python project in the working copy,
    # and beside it in a generated build
    $runtimeRoot = Get-Ao3Runtime -ProjectRoot $projectRoot
    $projectArg = Get-Ao3ProjectArg -ProjectRoot $projectRoot -RuntimeRoot $runtimeRoot

    # a build keeps config and logs in folders of their own; a working copy does not
    $configFolder = Set-Ao3Folders -RuntimeRoot $runtimeRoot -ProjectRoot $projectRoot

    Initialize-Ao3Config -Root $configFolder
    if (-not (Invoke-Ao3Sync -Root $projectRoot -Force:$Sync -SystemCerts:$SystemCerts)) { exit 1 }

    # a build ships the site prebuilt; a working copy has to compile it on the fly
    $prebuilt = Join-Path $runtimeRoot 'web'
    $servePrebuilt = Test-Path $prebuilt
    # gui_source is at the top of the working copy, above the runtime folder
    $guiSource = Join-Path (Split-Path $runtimeRoot -Parent) 'gui_source'

    if (-not $servePrebuilt) {
        if (-not (Test-Path $guiSource)) {
            Write-Problem "found neither a prebuilt web folder in $runtimeRoot nor $guiSource"
            exit 1
        }
        if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
            Write-Problem 'npm was not found. install node.js, then run this again.'
            exit 1
        }
        if (-not (Test-Path (Join-Path $guiSource 'node_modules'))) {
            Write-Step 'installing web dependencies (first run only)...'
            & npm --prefix $guiSource install
            if ($LASTEXITCODE -ne 0) {
                Write-Problem 'could not install web dependencies.'
                exit 1
            }
        }
    }

    Write-Host ''
    Write-Step 'starting the local helper in a separate window...'
    # $projectArg is relative on purpose: Start-Process joins ArgumentList without
    # quoting, so an absolute path containing spaces would be split into arguments.
    $helper = Start-Process -PassThru -WorkingDirectory $runtimeRoot -FilePath 'uv' `
        -ArgumentList @('run', '--project', $projectArg, '--no-sync',
                        'python', '-m', 'source_code.server')

    Start-Sleep -Seconds 2
    if ($helper.HasExited) {
        Write-Problem 'the local helper stopped immediately. the download buttons will not work.'
        Write-Problem 'try running it on its own to see why:'
        Write-Host '    uv run python -m source_code.server'
    }
    else {
        Write-Step "local helper running (pid $($helper.Id))"
    }

    Write-Host ''
    Write-Step "starting the web ui on http://localhost:$Port"
    Write-Step 'press ctrl+c to stop.'
    Write-Host ''

    # a relative --project only resolves from the runtime folder
    Push-Location $runtimeRoot
    try {
        if ($servePrebuilt) {
            # the app has no client side routes, so a plain static server is enough
            & uv run --project $projectArg --no-sync `
                python -m http.server $Port --directory $prebuilt --bind 127.0.0.1
        }
        else {
            & npm --prefix $guiSource start -- --port $Port
        }
    }
    finally {
        Pop-Location
    }
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
