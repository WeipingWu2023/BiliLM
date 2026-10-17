param([switch]$SkipInstall, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$frontendPath = Join-Path $PSScriptRoot 'frontend'
$dataPath = Join-Path $PSScriptRoot 'data'
$ownedProcesses = @()
try {
    foreach ($tool in @('python','node','npm.cmd','ffmpeg','ffprobe')) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing $tool. See README.md setup instructions." }
    }
    $checkPython = if (Test-Path -LiteralPath $pythonPath) { $pythonPath } else { 'python' }
    & $checkPython -c "import sys,struct; sys.exit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Use 64-bit Python 3.12. If python points to another version, create .venv with: py -3.12 -m venv .venv' }
    & node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 22 ? 0 : 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Node.js 22 or newer is required. See README.md.' }
    foreach ($port in @(3000,8000)) {
        $probe = New-Object System.Net.Sockets.TcpClient
        try { $probe.Connect('127.0.0.1',$port); throw "Port $port is occupied. Stop the existing service before starting BiliLM." }
        catch [System.Net.Sockets.SocketException] { }
        finally { $probe.Dispose() }
    }
    if (-not (Test-Path -LiteralPath $pythonPath)) { & python -m venv .venv; if ($LASTEXITCODE -ne 0) { throw 'venv failed' } }
    if (-not $SkipInstall) {
        & $pythonPath -m pip install --index-url https://pypi.org/simple -r backend/requirements.lock.txt
        if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
        Push-Location -LiteralPath $frontendPath
        try { & npm.cmd ci --registry=https://registry.npmjs.org; if ($LASTEXITCODE -ne 0) { throw 'npm dependency installation failed' } } finally { Pop-Location }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $frontendPath 'node_modules\next\dist\bin\next'))) { throw 'Run without -SkipInstall to install frontend dependencies' }
    New-Item -ItemType Directory -Force -Path $dataPath | Out-Null
    $env:PYTHONPATH = Join-Path $PSScriptRoot 'backend'
    $env:BILILM_DATA = $dataPath
    $ownedProcesses += Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataPath 'api.log') -RedirectStandardError (Join-Path $dataPath 'api-error.log')
    $ownedProcesses += Start-Process -FilePath $pythonPath -ArgumentList @('-m','app.worker') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataPath 'worker.log') -RedirectStandardError (Join-Path $dataPath 'worker-error.log')
    $ownedProcesses += Start-Process -FilePath (Get-Command node).Source -ArgumentList @('node_modules/next/dist/bin/next','dev','--hostname','127.0.0.1') -WorkingDirectory $frontendPath -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataPath 'frontend.log') -RedirectStandardError (Join-Path $dataPath 'frontend-error.log')
    $ready = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        foreach ($process in $ownedProcesses) { if ($process.HasExited) { throw 'A service stopped. Read data/*-error.log.' } }
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
            $page = Invoke-WebRequest 'http://127.0.0.1:3000' -UseBasicParsing -TimeoutSec 2
            if ($health.status -eq 'ok' -and $page.StatusCode -eq 200) { $ready = $true; break }
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'Startup timeout. Read data/*-error.log.' }
    Write-Host 'BiliLM: http://127.0.0.1:3000  (Ctrl+C to stop all services)'
    if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:3000' }
    while ($true) {
        foreach ($process in $ownedProcesses) { if ($process.HasExited) { throw 'A service stopped. Read data/*-error.log and restart to recover jobs.' } }
        Start-Sleep -Seconds 2
    }
} catch { Write-Error $_; exit 1 }
finally {
    foreach ($process in $ownedProcesses) {
        if (-not $process.HasExited) {
            # Python venv launchers and Next.js spawn children; terminate only owned process trees.
            & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
        }
    }
}
