# Shared Python discovery and process setup. No experiment starts on import.

function Resolve-PhdsimPython {
    param([string]$ProjectRoot, [switch]$RequireCnn)
    $taskCandidates = @((Join-Path $ProjectRoot '.venv\Scripts\python.exe'), 'D:\Doktorat\Platforma\.venv\Scripts\python.exe')
    foreach ($taskName in @('python', 'python3')) {
        $taskCommand = Get-Command $taskName -CommandType Application -ErrorAction SilentlyContinue
        if ($taskCommand) { $taskCandidates += $taskCommand.Source }
    }
    $taskCandidates += (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
    $taskProbe = if ($RequireCnn) { 'import sys, numpy, PIL, torch, torchvision; sys.exit(0 if sys.version_info >= (3,11) else 1)' } else { 'import sys, numpy, PIL; sys.exit(0 if sys.version_info >= (3,11) else 1)' }
    foreach ($taskCandidate in ($taskCandidates | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $taskCandidate -PathType Leaf) {
            try { & $taskCandidate -c $taskProbe 2>$null } catch { continue }
            if ($LASTEXITCODE -eq 0) { return $taskCandidate }
        }
    }
    throw 'Python 3.11+, numpy and Pillow are required; neural workflows also need torch and torchvision. See README.md.'
}

function Invoke-PhdsimPython {
    param([string]$ProjectRoot, [string]$Python, [string[]]$Arguments)
    $taskSavedPath = $env:PYTHONPATH
    $taskSavedNoBytecode = $env:PYTHONDONTWRITEBYTECODE
    $taskSavedMatplotlib = $env:MPLCONFIGDIR
    $env:PYTHONPATH = Join-Path $ProjectRoot 'src'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    if (-not $env:MPLCONFIGDIR) { $env:MPLCONFIGDIR = Join-Path ([IO.Path]::GetTempPath()) 'phdsim-matplotlib' }
    Push-Location -LiteralPath $ProjectRoot
    try {
        & $Python @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Python command failed with exit code $LASTEXITCODE." }
    } finally {
        Pop-Location
        $env:PYTHONPATH = $taskSavedPath
        $env:PYTHONDONTWRITEBYTECODE = $taskSavedNoBytecode
        $env:MPLCONFIGDIR = $taskSavedMatplotlib
    }
}
