[CmdletBinding()]
param(
    [ValidateSet('fetch', 'prepare', 'allocate', 'run', 'test', 'inspect', 'audit', 'cnn', 'learn')]
    [string]$Action = 'test',
    [string]$Data = 'D:\Doktorat\Platforma\data\pst900',
    [string]$Pool = '',
    [string]$Schedule = '',
    [string]$Output = '',
    [string]$AgentsConfig = 'configs\presence\agents.json',
    [string]$ProcessingConfig = 'configs\presence\experiment.json',
    [string]$AuditOutput = 'runs\pst900\audit',
    [string]$PerceptionConfig = 'configs\presence\perception_cnn.json',
    [string]$ModelDirectory = 'D:\Doktorat\Platforma\models\pst900_resnet18_v1',
    [string]$Models = '',
    [string]$LearningConfig = 'configs\presence\learning.json',
    [string]$LearningModelDirectory = 'D:\Doktorat\Platforma\models\pst900_learning_cnn_v1',
    [switch]$Trace,
    [string]$ReferenceRun = ''
)

$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
$taskNeedsCnn = $Action -in @('cnn', 'learn', 'test') -or [bool]$Models
$taskPython = Resolve-PhdsimPython -ProjectRoot $taskRoot -RequireCnn:$taskNeedsCnn
if (-not $Pool) { $Pool = Join-Path $Data $(if ($Action -in @('cnn', 'learn')) { 'pool_cnn_v1' } else { 'pool' }) }
if (-not $Schedule) { $Schedule = if ($Action -eq 'cnn') { 'runs\pst900_cnn\schedule.json' } else { 'runs\pst900\schedule.json' } }
if (-not $Output) { $Output = if ($Action -eq 'learn') { 'runs\pst900_learning' } elseif ($Action -eq 'cnn') { 'runs\pst900_cnn\results' } else { 'runs\pst900\results' } }
$taskOldPythonPath, $taskOldNoBytecode = $env:PYTHONPATH, $env:PYTHONDONTWRITEBYTECODE
$env:PYTHONPATH = Join-Path $taskRoot 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
Push-Location -LiteralPath $taskRoot
try {
    if ($Action -eq 'learn') {
        $taskArguments = @('-m','phdsim.cli','presence','learn-acquisition','--pool',$Pool,'--config',$LearningConfig,'--cnn-config',$PerceptionConfig,'--cnn-models',$LearningModelDirectory,'--output',$Output)
        if ($Trace) { $taskArguments += '--trace' }
        if ($ReferenceRun) { $taskArguments += @('--reference-run', $ReferenceRun) }
    } elseif ($Action -eq 'cnn') {
        if ((Test-Path -LiteralPath $Output) -and @(Get-ChildItem -LiteralPath $Output -Force).Count) { throw 'Results already exist. Set -Output to a new directory.' }
        if (-not (Test-Path -LiteralPath (Join-Path $Pool 'pool.json'))) {
            & $taskPython -m phdsim.cli review-pst900 --pool (Join-Path $Data 'pool') --output $Pool
            if ($LASTEXITCODE -ne 0) { throw 'Dataset review failed.' }
        }
        if (-not (Test-Path -LiteralPath (Join-Path $ModelDirectory 'models.json'))) {
            & $taskPython -m phdsim.cli train-cnn --pool $Pool --config $PerceptionConfig --output $ModelDirectory
            if ($LASTEXITCODE -ne 0) { throw 'CNN training failed.' }
        } else {
            & $taskPython -c 'import sys,json; from dataclasses import asdict; from pathlib import Path; from phdsim.perception import CnnConfig; configured=asdict(CnnConfig.load(sys.argv[1])); saved=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))["fit"]; sys.exit(0 if configured==saved else 1)' $PerceptionConfig (Join-Path $ModelDirectory 'models.json')
            if ($LASTEXITCODE -ne 0) { throw 'Saved models use different settings. Choose a new -ModelDirectory for this configuration.' }
        }
        if (-not (Test-Path -LiteralPath $Schedule)) {
            & $taskPython -m phdsim.cli allocate --pool $Pool --agents $AgentsConfig --schedule $Schedule
            if ($LASTEXITCODE -ne 0) { throw 'Agent allocation failed.' }
        }
        $taskArguments = @('-m','phdsim.cli','presence','run','--pool',$Pool,'--schedule',$Schedule,'--processing',$ProcessingConfig,'--output',$Output,'--models',$ModelDirectory)
    } else {
      $taskArguments = switch ($Action) {
        'inspect' { @('-m','phdsim.cli','presence','inspect','--data',$Data) }
        'fetch' { @('-m','phdsim.cli','presence','fetch','--data',$Data) }
        'prepare' { @('-m','phdsim.cli','presence','prepare-pst900','--data',$Data,'--pool',$Pool) }
        'allocate' { @('-m','phdsim.cli','presence','allocate','--pool',$Pool,'--agents',$AgentsConfig,'--schedule',$Schedule) }
        'run' { @('-m','phdsim.cli','presence','run','--pool',$Pool,'--schedule',$Schedule,'--processing',$ProcessingConfig,'--output',$Output) }
        'test' { @('-m','unittest','discover','-v') }
        'audit' { @((Join-Path $PSScriptRoot 'audit_pst900.py'),'--pool',$Pool,'--results',$Output,'--output',$AuditOutput) }
      }
      if ($Action -eq 'run' -and $Models) { $taskArguments += @('--models',$Models) }
    }
    & $taskPython @taskArguments
    $taskExitCode = $LASTEXITCODE
} finally {
    Pop-Location
    $env:PYTHONPATH, $env:PYTHONDONTWRITEBYTECODE = $taskOldPythonPath, $taskOldNoBytecode
}
exit $taskExitCode
