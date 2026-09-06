<#
.SYNOPSIS
    Shared setup for run-local.ps1 and run-gui.ps1.

.DESCRIPTION
    ao3downloader resolves settings.ini, data.json, logs/ and a relative DownloadFolder
    against the working directory. Both launchers therefore have to run from the root of
    this working copy and use the config sitting there. Keeping that in one place is what
    stops the two scripts from drifting apart.
#>

function Write-Step($message) {
    Write-Host $message -ForegroundColor Cyan
}

function Write-Problem($message) {
    Write-Host $message -ForegroundColor Yellow
}

function Get-Ao3Root {
    <#
        The working copy root, found from wherever this script lives. The launchers sit in
        powershell_source/, but a generated build puts them next to the project instead, so
        both the script's own folder and its parent are checked.
    #>
    param([Parameter(Mandatory)] [string] $ScriptRoot)

    $start = $ScriptRoot
    if (-not $start) { $start = (Get-Location).Path }
    $parent = Split-Path $start -Parent

    # the launchers sit in different places - powershell_source for the console one,
    # helper_scripts for the web one, and a generated build where everything is flat - so
    # check this script's folder, the helper folder under it, and the same from the parent.
    $candidates = @(
        $start,
        (Join-Path $start 'ao3_download_helper'),
        (Join-Path $start 'powershell_source\ao3_download_helper'),
        $parent,
        $(if ($parent) { Join-Path $parent 'powershell_source\ao3_download_helper' })
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path (Join-Path $candidate 'pyproject.toml'))) {
            return $candidate
        }
    }

    Write-Problem "could not find pyproject.toml near $start"
    Write-Problem 'this script has to stay in the ao3downloader working copy.'
    return $null
}

function Get-Ao3Runtime {
    <#
        Where settings.ini, data.json, logs\ and a relative DownloadFolder live.

        In the working copy the python project sits one level below them, in
        ao3_download_helper. A generated build is flat, so the two are the same folder.
    #>
    param([Parameter(Mandatory)] [string] $ProjectRoot)

    if ((Split-Path $ProjectRoot -Leaf) -eq 'ao3_download_helper') {
        return (Split-Path $ProjectRoot -Parent)
    }
    return $ProjectRoot
}

function Get-Ao3ProjectArg {
    <#
        What to pass to `uv --project`, relative to the runtime folder.

        Deliberately relative: Start-Process joins its ArgumentList without quoting, so an
        absolute path containing spaces would be split into separate arguments.
    #>
    param(
        [Parameter(Mandatory)] [string] $ProjectRoot,
        [Parameter(Mandatory)] [string] $RuntimeRoot
    )

    if ($ProjectRoot -eq $RuntimeRoot) { return '.' }
    return (Split-Path $ProjectRoot -Leaf)
}

function Set-Ao3Folders {
    <#
        Tell the application where its settings and logs live.

        A generated build keeps them apart - config\ beside the launcher, logs\ with the
        python - so it says so through the environment. A working copy keeps everything in
        the runtime folder, where the application looks by default, so nothing is set.

        Returns the folder that settings.ini and data.json will be written to.
    #>
    param(
        [Parameter(Mandatory)] [string] $RuntimeRoot,
        [Parameter(Mandatory)] [string] $ProjectRoot
    )

    $configFolder = Join-Path $RuntimeRoot 'config'
    if (-not (Test-Path $configFolder)) {
        # working copy: the defaults already point at the runtime folder
        Remove-Item Env:\AO3DOWNLOADER_CONFIG_FOLDER -ErrorAction SilentlyContinue
        Remove-Item Env:\AO3DOWNLOADER_LOG_FOLDER -ErrorAction SilentlyContinue
        return $RuntimeRoot
    }

    $env:AO3DOWNLOADER_CONFIG_FOLDER = $configFolder
    $env:AO3DOWNLOADER_LOG_FOLDER = $ProjectRoot
    return $configFolder
}

function Test-Ao3Uv {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        # the .local\bin case: uv is installed but this session started before it was on PATH
        $uvPath = Join-Path $env:USERPROFILE '.local\bin'
        if (Test-Path (Join-Path $uvPath 'uv.exe')) {
            $env:PATH = "$uvPath;$env:PATH"
        }
    }

    if (Get-Command uv -ErrorAction SilentlyContinue) { return $true }

    Write-Problem 'uv is required but was not found.'
    Write-Problem 'install it with:'
    Write-Host '    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
    Write-Problem 'then open a new terminal and run this script again.'
    return $false
}

function Initialize-Ao3Config {
    param([Parameter(Mandatory)] [string] $Root)

    $settingsFile = Join-Path $Root 'settings.ini'
    $dataFile = Join-Path $Root 'data.json'

    if (Test-Path $settingsFile) {
        Write-Step "settings.ini: $settingsFile"
    }
    else {
        $template = Join-Path $Root 'ao3downloader\settings\settings.ini'
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
        $match = Select-String -Path $settingsFile -Pattern '^\s*DownloadFolder\s*=\s*(.*)$' |
            Select-Object -First 1
        if ($match) {
            Write-Step "downloads:    $($match.Matches.Groups[1].Value.Trim()) (set in settings.ini)"
        }
    }
}

function Invoke-Ao3Sync {
    param(
        [Parameter(Mandatory)] [string] $Root,
        [switch] $Force,
        [switch] $SystemCerts
    )

    $needsSync = $Force -or -not (Test-Path (Join-Path $Root '.venv'))
    if (-not $needsSync) { return $true }

    Write-Step 'installing dependencies...'
    $syncArgs = @('sync', '--project', $Root, '--python', '3.12')
    if ($SystemCerts) { $syncArgs += '--system-certs' }

    & uv @syncArgs
    if ($LASTEXITCODE -eq 0) { return $true }

    if ($SystemCerts) {
        Write-Problem 'could not install dependencies.'
        return $false
    }

    # the usual cause is a network that intercepts TLS, so retry against the
    # Windows certificate store before giving up
    Write-Problem 'dependency install failed. retrying with the Windows certificate store...'
    & uv @syncArgs --system-certs
    if ($LASTEXITCODE -ne 0) {
        Write-Problem 'could not install dependencies.'
        return $false
    }
    return $true
}
