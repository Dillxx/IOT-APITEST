# 结构简化验证记录

验证日期：2026-10-16。Windows、Python 3.12.14、pytest 9.1.1。沿用 requirements.lock，未升级依赖。

## 调整结果

- 用例只保留操作和验证；登录、原状态记录、恢复、资源关闭由 fixture 管理。
- Harness、HdmiApi、DeviceApi、DeviceSession 合并为直接使用的 DeviceClient。
- 原 api/protocol/core/flows 和单独断言层已合并；HTTP 和 WS 保留必要的传输职责边界。
- Python 文件由 47 减少到 22，包含包标记和原占位目录，不代表业务逻辑减少一半。
- 全局 conftest 不再包含 HDMI 数据钩子和音量恢复；数据绑定在测试文件，前后置在 audio/conftest.py。
- Windows PowerShell 5 脚本补充 UTF-8 BOM，避免中文编码导致解析失败。未修改系统执行策略；本次通过进程级 ExecutionPolicy Bypass 验证。

## 验证结果

| 检查 | 结果 |
|---|---|
| 调整前完整回归 | 20 passed |
| 重构后保留原回归 | 20 passed |
| 新增前后置失败恢复检查后 | 22 passed |
| run-tests.ps1 完整入口 | 22 passed |
| Python 开发模式、asyncio 调试 | 22 passed |
| pip check | No broken requirements found |
| 两条 JSON 数据 10/20 | 2 passed，分别恢复原音量 30 |
| IOT_HDMI_VOLUME=25 覆盖 | 通过，源 JSON 未修改 |
| 布尔值误作音量 | 收集阶段明确拒绝 |
| --live 缺少凭据 | 网络操作前退出，返回码 4 |
| 旧模块导入与语法检查 | 未发现旧导入，Python 语法可解析 |

新增生命周期回归启动独立 pytest 探针：业务断言失败后仍恢复；恢复被拒绝时报告 teardown error，仍关闭资源。探针中的故意失败由外层测试检查，完整回归为通过。

完整报告：[junit.xml](../artifacts/20261016-092308-55518390/junit.xml)。

多数据报告：[multi.xml](../artifacts/simplification-validation/multi.xml)。

额外检查汇总：[summary.json](../artifacts/simplification-validation/summary.json)。

重构前源码快照：[before-simplification-20261016-091934.zip](../artifacts/before-simplification-20261016-091934.zip)。其中不包含 .venv、历史 artifacts 和 IDE 缓存；原项目无 Git 仓库。

本次全部使用本地模拟，没有执行真实设备控制。报告状态不等于物理声音效果；服务器到终端 TCP 行为仍未验证。
