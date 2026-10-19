[CmdletBinding()]
param(
    [ValidateSet('all', 'pstnet', 'presence')]
    [string]$Workflow = 'all',
    [string]$Output = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Resolve-PhdsimPython -ProjectRoot $taskRoot -RequireCnn
$taskArguments = @('-m', 'phdsim.walkthrough', '--workflow', $Workflow)
if ($Output) { $taskArguments += @('--output', $Output) }
Invoke-PhdsimPython -ProjectRoot $taskRoot -Python $taskPython -Arguments $taskArguments
