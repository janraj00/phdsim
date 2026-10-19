[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Resolve-PhdsimPython -ProjectRoot $taskRoot -RequireCnn
Invoke-PhdsimPython -ProjectRoot $taskRoot -Python $taskPython -Arguments @('-m', 'unittest', 'discover', '-s', 'tests', '-v')
