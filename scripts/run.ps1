# Compatibility with earlier presence experiments. Prefer presence.ps1 or pstnet.ps1.
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'presence.ps1') @args
exit $LASTEXITCODE
