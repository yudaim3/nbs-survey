param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { & $launcher.Source -3 -m venv .venv }
    else {
        $launcher = Get-Command python -ErrorAction SilentlyContinue
        if (-not $launcher) { throw 'Python 3.12以上をインストールしてください。README.mdを参照してください。' }
        & $launcher.Source -m venv .venv
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $taskPython)) { throw 'Python環境を作成できませんでした。' }
}
& $taskPython -m pip install -r requirements.txt --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw 'ライブラリーをインストールできませんでした。' }
try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2
    if ($health.app -eq 'nbs-workation') {
        if (-not $NoBrowser) { Start-Process 'http://localhost:8765/admin' }
        return
    }
} catch {}
& (Join-Path $PSScriptRoot 'stop-python.ps1')
$env:ALLOW_ADMIN_SETUP = 'true'
$env:PYTHONIOENCODING = 'utf-8'
$serverPath = Join-Path $PSScriptRoot 'server.py'
$taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('"' + $serverPath + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'server.log') -RedirectStandardError (Join-Path $PSScriptRoot 'server-error.log') -PassThru
$taskProcess.Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'server.pid')
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2
        if ($health.app -eq 'nbs-workation') {
            if (-not $NoBrowser) { Start-Process 'http://localhost:8765/admin' }
            return
        }
    } catch {}
    if ($taskProcess.HasExited) { break }
}
throw '起動できませんでした。server-error.logを確認してください。'
