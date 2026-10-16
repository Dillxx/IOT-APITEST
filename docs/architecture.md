# 当前结构与职责

## 用例只保留操作和验证

用例直接接收 `hdmi_device`，调用操作并断言返回状态，不展示登录、连接、原状态读取或恢复。

```python
after = await hdmi_device.set_volume(hdmi_case["target_volume"])
assert type(after["HDMI_audio_status"]) is int
assert after["HDMI_audio_status"] == hdmi_case["expected_volume"]
```

其他通道与 `hdmi_device.initial_state` 的比较也在用例中，属于验证。initial_state 由 fixture 提前读取。

## 只有必要的调用层次

```text
测试 → DeviceClient → HttpClient / WsClient → HTTPX / websockets
```

DeviceClient 同时提供 HTTP 设备核对和 WS 操作，没有 Harness、HdmiApi、DeviceApi、DeviceSession 的中间转发。报文常量、公共字段、登录、心跳和设备方法都在 clients/device.py，可在一个文件内追踪。

保留独立 WsClient 是因为设备会插入日志、心跳和状态推送。它只负责一条连接上的消息接收、历史、游标和超时，不认识 HDMI。DeviceClient 决定哪些消息属于登录、确认或目标状态。

## 前后置

- tests/conftest.py：注册运行选项、检查真机条件、加载配置、创建证据、提供 device_factory。
- tests/audio/conftest.py：提供 hdmi_device；获取和校验原音量，保存 initial_state，结束后恢复并复核。
- device_factory 用 AsyncExitStack 登记已创建的资源，准备阶段失败也会关闭连接和模拟器。
- 恢复失败不吞掉，显示 teardown 错误；未知控制结果不自动重发。

## 数据

测试文件内的 pytest_generate_tests 负责绑定 hdmi_case，路径明确来自 --iot-data；support/data.py 只读取、检查和复制数据。保留这个短钩子是为了在收集阶段支持命令行选择 JSON，而不是将运行配置隐藏到导入期。

## 旧路径迁移

| 旧实现 | 当前实现 |
|---|---|
| api/audio/hdmi.py + protocol/websocket/session.py | clients/device.py |
| api/devices.py + protocol/http/devices.py | clients/device.py |
| protocol/websocket/messages.py | clients/device.py 中的报文定义 |
| core/http/client.py | clients/http.py |
| core/websocket/client.py | clients/websocket.py |
| assertions/audio/hdmi.py | 简单断言直接写在用例和恢复处 |
| support/data_loader/json_loader.py | support/data.py |
| support/evidence/recorder.py | support/evidence.py |
| Harness + hdmi_context | 直接提供 DeviceClient 的 hdmi_device |

未实现的 api/flows/protocol 占位层已移除。未来出现重复复杂断言或实际新业务时再提取；不为尚未实现的能力建立多层目录。

clients 不依赖 tests 或 mocks；底层通信只依赖证据工具和第三方库。配置不依赖设备客户端。
