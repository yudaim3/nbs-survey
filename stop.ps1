$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $PSScriptRoot 'server.pid'
if (Test-Path -LiteralPath $pidFile) {
    $taskPid = [int](Get-Content -LiteralPath $pidFile)
    $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$taskPid" -ErrorAction SilentlyContinue
    if ($taskProcess -and $taskProcess.CommandLine -match 'server.py' -and $taskProcess.ExecutablePath -match 'python') { Stop-Process -Id $taskPid }
    Remove-Item -LiteralPath $pidFile
}
