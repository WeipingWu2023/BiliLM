param([string[]]$Models = @('medium','large-v3','turbo'), [switch]$IncludeSenseVoice)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run start.cmd once to create the Python environment, then stop BiliLM before installing optional models.' }
if ($IncludeSenseVoice) {
    $probe = New-Object System.Net.Sockets.TcpClient
    try { $probe.Connect('127.0.0.1',8000); throw 'Stop BiliLM with Ctrl+C before installing SenseVoice dependencies.' }
    catch [System.Net.Sockets.SocketException] { }
    finally { $probe.Dispose() }
    & $pythonPath -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.8.0 torchaudio==2.8.0
    if ($LASTEXITCODE -ne 0) { throw 'PyTorch CPU installation failed' }
    & $pythonPath -m pip install --index-url https://pypi.org/simple -c backend/requirements.lock.txt -r backend/requirements-sensevoice.txt
    if ($LASTEXITCODE -ne 0) { throw 'SenseVoice dependency installation failed' }
}
$env:PYTHONPATH = Join-Path $PSScriptRoot 'backend'
$arguments = @('scripts/prepare_models.py','--models') + $Models
if ($IncludeSenseVoice) { $arguments += '--sensevoice' }
& $pythonPath @arguments
if ($LASTEXITCODE -ne 0) { throw 'Model preparation failed; cached downloads are retained for retry' }
& $pythonPath -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency compatibility check failed' }
Write-Host 'Models are prepared. Run start.cmd to use BiliLM. Accuracy still requires verified references.'
