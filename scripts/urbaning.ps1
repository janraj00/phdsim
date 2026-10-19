[CmdletBinding()]
param(
    [ValidateSet('fetch', 'extract', 'inspect')]
    [string]$Action = 'inspect',
    [string]$DataRoot = 'D:\Doktorat\Platforma\data\urbaning-v2x',
    [string]$Sequence = '20241126_0017_crossing1_00',
    [string]$Output = 'runs\urbaning_inspection',
    [int]$Frame = 100
)

$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
$taskPython = Resolve-PhdsimPython -ProjectRoot $taskRoot
$taskArguments = @('-m', 'phdsim.cli', 'urbaning', $Action, '--root', $DataRoot,
                   '--sequence', $Sequence, '--output', $Output, '--frame', $Frame.ToString())
Invoke-PhdsimPython -ProjectRoot $taskRoot -Python $taskPython -Arguments $taskArguments
