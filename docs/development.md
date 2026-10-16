# 开发约定

## 可读性

测试只保留操作和验证；前后置由 fixture 负责。设备操作集中在 clients/device.py；不要再引入仅仅转发调用的 API/Session/容器。测试数据绑定放在相关测试附近。复杂并且重复的代码才提取公共方法。

HTTP 请求、业务成功码与目标设备核对仍分别检查。错误文本和证据不能泄露凭据或签名 URL。

## WebSocket

1. 每连接只有一个接收任务；等待者读取共享消息历史。
2. 发送前记录游标，不能把任意下一条消息当成对应回包。
3. 允许状态先于确认消息、日志和业务心跳插入；分别匹配类型、成功码和值。
4. 同一设备操作串行；当前协议没有显式请求流水号，迟到消息仍存在关联边界。
5. 超时、断线、非法消息明确失败；控制结果不确定后禁止继续控制和自动重试。
6. 历史被淘汰时明确报错，不猜测成功。
7. 业务 heartbeat 在 DeviceClient；WebSocket Ping/Pong 由通信库管理。

## 前后置和配置

每条 HDMI 用例单独读取原状态，按 restore_original 决定是否恢复并复核。恢复失败必须报告 teardown 错误，连接清理仍执行。

环境地址和超时放 config/environments；设备身份能力放 config/devices；目标与预期放 testdata；凭据只取环境变量。0..100 当前是暂定保护范围。

默认模拟。真机需要显式 --live 和有效凭据；禁止真机 xdist 并行。跨独立进程的设备锁尚未实现。

## 验证

修改通信或 fixture 后，运行完整回归和 asyncio 调试检查：

```powershell
.\run-tests.ps1
& '.\.venv\Scripts\python.exe' -X dev -m pytest --asyncio-debug -q
& '.\.venv\Scripts\python.exe' -m pip check
```

保留乱序、旧消息、超时、断线、心跳、清理和脱敏回归。test_fixture_lifecycle.py 的子进程会故意失败；外层检查失败被正确报告、恢复和关闭均执行，因此完整回归应通过。

当前只证明协议模拟和报告值；真机控制、物理声音效果和服务器到终端 TCP 行为未验证。
