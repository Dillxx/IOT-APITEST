# 9220 HTTP + WebSocket 接口自动化

用例只写操作和验证，fixture 管理前后置。默认运行本地模拟服务，显式 `-Live` / `--live` 才允许访问实际设备。

## 从哪里开始

先打开 [HDMI 用例](tests/audio/test_9220_hdmi.py)，再按需要查看：

- [用例数据](testdata/audio/hdmi.json)：目标、预期、其他通道检查开关。
- [音频前后置](tests/audio/conftest.py)：原状态、恢复、恢复失败报告。
- [设备操作](clients/device.py)：HTTP 设备核对、WS 登录、状态查询、设置音量。
- [阅读和编写说明](docs/reading-and-writing.md)、[结构说明](docs/architecture.md)。

测试中直接 `await hdmi_device.set_volume(...)`，拿到最终复核状态后使用 `assert` 检查。不再解包 Harness，也不再经过 api → protocol → session 的多层对象。

## 运行和断点调试

在项目根目录执行，使用现有 Python 3.12 虚拟环境：

```powershell
.\run-tests.ps1
.\run-tests.ps1 -TestPath 'tests/audio/test_9220_hdmi.py'
.\run-tests.ps1 -TestPath 'tests/framework'
```

VS Code：打开整个项目文件夹，在用例可执行行设置断点，按 Ctrl+Shift+D，选择“调试 HDMI 用例（本地模拟）”，按 F5。配置已固定使用 `.venv/Scripts/python.exe` 和 `-m pytest`。

暂停在 `after = await ...` 时，该行尚未执行；执行后再查看 `after`。可观察 `hdmi_case`、`hdmi_device.initial_state` 和 `after`。

每次脚本运行生成独立 artifacts 目录，包含 junit.xml 和每条用例的脱敏 traffic.jsonl。用例结束后，日志中应能找到原音量恢复检查点。

## 项目结构

```text
tests/
  conftest.py                 # 公共选项、配置、证据、设备创建与关闭
  audio/
    conftest.py               # 音频前后置
    test_9220_hdmi.py          # 本文件的数据绑定、操作、断言
  framework/                  # 乱序、超时、断线、恢复、脱敏等回归
clients/
  device.py                   # 集中的设备操作入口与业务报文
  http.py                     # HTTPX 请求、错误处理、脱敏日志
  websocket.py                # 唯一接收任务、共享消息历史、条件等待
support/
  data.py                     # JSON 数据读取、检查和目标值覆盖
  evidence.py                 # 脱敏与证据写入
config/                       # 环境、设备 TOML 及加载器
testdata/audio/hdmi.json       # 测试输入和期望
mocks/device_server.py        # 本地模拟器和故障开关
```

## 数据和运行设置

| 内容 | 位置 |
|---|---|
| 服务地址、超时、恢复策略 | config/environments/test.toml |
| MAC、型号、能力、暂定保护范围 | config/devices/ts9220.toml |
| 用例 id、目标音量、预期音量 | testdata/audio/hdmi.json |
| Token / HTTP sign / WS sign | IOT_TOKEN / IOT_SIGN / IOT_WS_SIGN 环境变量 |

测试文件内的 `pytest_generate_tests` 明确读取 `--iot-data`，把 JSON 中每条 cases 记录绑定到 hdmi_case。数据绑定保留在测试文件附近，不在全局钩子中猜测参数归属。

```powershell
.\run-tests.ps1 -Config 'config/environments/test.toml' -Data 'testdata/audio/hdmi.json'
```

`IOT_HDMI_VOLUME` 可覆盖本次输入和期望，不改写源 JSON。设备配置路径相对环境 TOML 解析。

## 实际设备

核对环境和设备后，在本地终端提供有效凭据，再显式启用：

```powershell
$env:IOT_TOKEN = '<有效Token>'
$env:IOT_SIGN = '<有效HTTP sign>'
.\run-tests.ps1 -Live -TestPath 'tests/audio/test_9220_hdmi.py'
```

缺失凭据在联网前退出；真机禁止 xdist 并行。同一终端不要运行多个独立控制进程。HTTP sign 与 WS sign 分开，需要时设置 IOT_WS_SIGN。当前不包含账号登录和凭据自动获取。

控制结果不确定时禁止继续控制或自动重放；恢复失败显示 teardown 错误并保留原值。当前报告值一致不等于物理声音测量。0..100 仍是暂定保护范围，`range_confirmed=false`，不是已确认协议边界。本次重构未执行真机。

## 验证和依赖

```powershell
& '.\.venv\Scripts\python.exe' -X dev -m pytest --asyncio-debug -q
& '.\.venv\Scripts\python.exe' -m pip check
```

沿用 requirements.lock，未升级依赖。重构记录见 [validation.md](docs/validation.md)。协议依据来自 `../outputs/iot-capture-20261008-01/9220-hdmi-volume-10-evidence.json`。
