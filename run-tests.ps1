# 统一运行入口；环境、协议、文件、类别和数据 ID 可组合筛选。
param(
    [switch]$Live,
    [string]$Env,
    [string]$Config,
    [string]$AuthHar,
    [string[]]$TestPath = @('tests'),
    [ValidateSet('http', 'websocket')][string]$Protocol,
    [ValidateSet('normal', 'rejected', 'special')][string]$Category,
    [string[]]$CaseId,
    [string]$Data
)

$ErrorActionPreference = 'Stop'
if ($PSBoundParameters.ContainsKey('AuthHar')) {
    throw '-AuthHar was removed. Configure config/accounts.local.toml or IOT_USERNAME/IOT_PASSWORD.'
}
if ($PSBoundParameters.ContainsKey('Data')) {
    throw '-Data was removed. Edit data/<protocol>/<interface>.json and select -CaseId.'
}
if ($Env -and $Config) {
    throw '-Env and -Config cannot be combined.'
}
if (-not $Live -and $env:PYTEST_ADDOPTS -match '(^|\s)--live(\s|$)') {
    throw 'Implicit --live in PYTEST_ADDOPTS is not allowed. Pass -Live explicitly.'
}

# 固定使用项目虚拟环境，不依赖系统 Python 或终端是否激活环境。
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Missing .venv. Create Python 3.12+ environment and install requirements.lock.'
}
$runName = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0, 8))
$runDirectory = Join-Path $PSScriptRoot ('artifacts\' + $runName)
$testArguments = @('-m', 'pytest') + $TestPath + @(
    '--iot-artifacts', $runDirectory,
    '--junitxml', (Join-Path $runDirectory 'junit.xml')
)
if ($Env) { $testArguments += @('--env', $Env) }
if ($Config) { $testArguments += @('--iot-config', $Config) }
if ($Protocol) { $testArguments += @('--protocol', $Protocol.ToLowerInvariant()) }
if ($Category) { $testArguments += @('--category', $Category.ToLowerInvariant()) }
foreach ($id in $CaseId) { $testArguments += @('--case-id', $id) }
if ($Live) { $testArguments += '--live' }

# 切到项目根目录运行，结束后恢复原工作目录并返回真实退出码。
Push-Location $PSScriptRoot
try {
    & $pythonExe @testArguments
    $testExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
Write-Host "Run artifacts: $runDirectory"
exit $testExitCode
