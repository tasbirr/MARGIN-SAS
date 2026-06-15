param(
    [switch]$Run,
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"

function Test-PythonVersion {
    param(
        [string]$Command,
        [string[]]$Args
    )

    $versionText = & $Command @Args -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    try {
        $version = [version]$versionText
    } catch {
        return $false
    }

    if ($version.Major -ne 3) {
        return $false
    }

    if ($version.Minor -lt 10 -or $version.Minor -gt 13) {
        return $false
    }

    return $true
}

function Get-PythonCommand {
    if ($PythonPath) {
        if (Test-PythonVersion -Command $PythonPath -Args @()) {
            return @{ Command = $PythonPath; Args = @() }
        }
    }

    $candidates = @(
        @{ Command = "py"; Args = @("-3.11") },
        @{ Command = "py"; Args = @("-3.12") },
        @{ Command = "py"; Args = @("-3.13") },
        @{ Command = "py"; Args = @("-3.10") },
        @{ Command = "python"; Args = @() },
        @{ Command = "python3"; Args = @() }
    )

    foreach ($candidate in $candidates) {
        if (Test-PythonVersion -Command $candidate.Command -Args $candidate.Args) {
            return $candidate
        }
    }

    return $null
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

try {
    $pythonCmd = Get-PythonCommand
    if (-not $pythonCmd) {
        Write-Error "Python 3.10-3.13 is required. Install Python 3.11 (or 3.13) and retry, or pass -PythonPath C:\\path\\to\\python.exe."
    }

        $venvPython = Join-Path $repoRoot ".venv\\Scripts\\python.exe"
        $recreateVenv = $false

        if (Test-Path $venvPython) {
            if (-not (Test-PythonVersion -Command $venvPython -Args @())) {
                $recreateVenv = $true
            }
        }

        if (-not (Test-Path ".venv") -or $recreateVenv) {
            if ($recreateVenv) {
                Remove-Item -Recurse -Force .venv
            }
            & $pythonCmd.Command @($pythonCmd.Args) -m venv .venv
        }

    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    & $venvPython -m pip install -r requirements.txt
    & $venvPython scripts\doctor.py

    if ($Run) {
        & $venvPython run_server.py
    }
} finally {
    Pop-Location
}
