param([int]$Port = 5000, [string]$DataDir = "")
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv-dev\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Create a Python 3.12+ virtual environment and install requirements.txt first. See README.md.' }
$taskArguments = @((Join-Path $PSScriptRoot 'app.py'), '--port', "$Port")
if ($DataDir) { $taskArguments += @('--data-dir', $DataDir) }
& $taskPython @taskArguments
exit $LASTEXITCODE
