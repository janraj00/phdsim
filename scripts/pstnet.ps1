[CmdletBinding()]
param(
    [ValidateSet('status', 'prepare', 'cache', 'learn', 'run', 'train-rgb')]
    [string]$Action = 'status',
    [string]$Config = 'configs\pstnet\experiment.json',
    [double]$Cost = 0.005,
    [string]$Output = '',
    [string]$TrainingConfig = 'configs\pstnet\rgb_pilot.json',
    [string]$ModelDirectory = 'D:\Doktorat\Platforma\models\pstnet_rgb_pilot_v1'
)

$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
$taskPython = Resolve-PhdsimPython -ProjectRoot $taskRoot -RequireCnn
$taskArguments = @('-m', 'phdsim.cli', 'pstnet', $Action, '--config', $Config, '--cost', $Cost.ToString([Globalization.CultureInfo]::InvariantCulture))
if ($Output) { $taskArguments += @('--output', $Output) }
if ($Action -eq 'train-rgb') { $taskArguments += @('--training-config', $TrainingConfig, '--model-directory', $ModelDirectory) }
Invoke-PhdsimPython -ProjectRoot $taskRoot -Python $taskPython -Arguments $taskArguments
