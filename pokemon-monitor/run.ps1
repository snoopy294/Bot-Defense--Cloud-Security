# Activates the local venv (if present) and runs the monitor.
# Used by the scheduled task; you can also run it directly: .\run.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
if (Test-Path $venvPy) {
    & $venvPy "monitor.py"
} else {
    # Fall back to whatever python is on PATH (pythonw = no console window).
    $pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue)
    if ($pythonw) { & $pythonw.Source "monitor.py" }
    else { & python "monitor.py" }
}
