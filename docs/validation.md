# API 与用例分离验收

日期：2026-10-16。API 单独定义，用例及关联流程调用 API 展示业务步骤，断言保留在测试中。仅使用本地模拟，未运行实际设备。

## 改动

- api/http/device_list.py：定义设备列表的 HTTP 方法和路径，返回完整 HTTPX Response。
- api/websocket/hdmi.py：定义控制和状态查询请求，返回实际业务回包。
- api/websocket/session.py：定义业务登录及设备信息请求，供前置和关联流程复用。
- 用例移除请求路径和 actioncode，明确调用 API；状态等待和断言仍可见。
- 登录、身份核对、原状态读取和恢复由前置辅助通过 API 执行，公共通信不导入 API。
- 数据结构、case ID、执行选项、共享连接与逐条恢复策略均保持。

## 验证

| 检查 | 结果 |
|---|---|
| 修改前基线 | 53 passed |
| 修改后完整回归 | 59 passed |
| 开发模式、asyncio 调试 | 59 passed |
| 统一脚本 -Category normal | HTTP、WS、关联流程共 3 passed |
| API 拒绝回包和负数/小数/空值输入 | 4 项模拟回归通过 |
| API 不隐藏查询、不自动断言确认值或状态值 | 通过 |
| HTTP API 返回实际错误响应、透传请求选项 | 通过 |
| 正式 HDMI 与关联流程的业务请求序列 | 与前版一致，包含设置 10 与恢复 30 |
| 中文注释、三引号说明排版 | 36 个 Python 文件静态检查通过 |
| 依赖检查 | No broken requirements found，锁文件不变 |

59 项包含 3 条正式接口/流程用例与 56 项框架回归。额外 6 项只验证 API 边界，不新增或推断真实设备的非法输入预期。

## 报告与回退依据

- [完整报告](../artifacts/api-separation-validation/full.xml)
- [asyncio 调试报告](../artifacts/api-separation-validation/debug.xml)
- [正式接口与流程报告](../artifacts/20261016-141431-3ca959c2/junit.xml)
- [本次验收汇总](../artifacts/api-separation-validation/summary.json)
- [本次源码快照](../artifacts/before-api-separation-20261016-141000.zip)
- [前次整体目录重构验收汇总](../artifacts/interface-refactor-validation/summary.json)

完整回归的请求日志目录：`artifacts/20261016-141313-41ab7ada`。

当前正式 HDMI 数据仍仅为音量 10；其他输入的真实成功、拒绝、限幅或取整规则仍待确认。物理声音、真机执行和服务器到终端 TCP 未验证。
