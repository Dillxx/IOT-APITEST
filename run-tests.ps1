# Windows 运行入口：默认本地模拟，只有 -Live 才启用真机控制。
# Config 指定环境，Data 指定参数数据，TestPath 可缩小本次执行范围。
param(
    [switch]$Live,
    [string]$Config = (Join-Path $PSScriptRoot 'config\environments\test.toml'),
    [string]$Data = (Join-Path $PSScriptRoot 'testdata\audio\hdmi.json'),
    [string]$TestPath = 'tests'
)

$ErrorActionPreference = 'Stop'
# 使用项目独立环境，避免误用系统 Python 或其他项目的依赖。
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Missing .venv. Create it with Python 3.12+ and install requirements.lock; see README.md.'
}
# 时间加随机编号，为每次运行建立独立目录，避免覆盖历史证据。
$runName = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0, 8))
$runDirectory = Join-Path $PSScriptRoot ('artifacts\' + $runName)
New-Item -ItemType Directory -Path $runDirectory | Out-Null
# 向 pytest 传入参数，JUnit 报告与逐用例 JSONL 使用同一个运行目录。
$testArguments = @('-m', 'pytest', $TestPath, '--iot-config', $Config, '--iot-data', $Data,
    '--iot-artifacts', $runDirectory, '--junitxml', (Join-Path $runDirectory 'junit.xml'))
if ($Live) {
    $testArguments += '--live'
}
Push-Location $PSScriptRoot
try {
    # @testArguments 展开数组为命令参数，无需手工拼接带空格的文件路径。
    & $pythonExe @testArguments
    $testExitCode = $LASTEXITCODE
} finally {
    # 测试成功或失败都要恢复执行脚本之前的工作目录。
    Pop-Location
}
Write-Host "Run artifacts: $runDirectory"
# 返回 pytest 的退出码，让终端或流水线正确识别测试失败。
exit $testExitCode

