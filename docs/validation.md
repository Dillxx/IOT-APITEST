# 接口组织重构验收

日期：2026-10-16。Python 3.12.14、pytest 9.1.1，依赖锁未改变。本次只使用本地模拟，没有执行真机控制。

## 结果

| 检查 | 结果 |
|---|---|
| 重构前基线 | 22 passed |
| 统一 run-tests.ps1 完整入口 | 53 passed |
| Python 开发模式、asyncio 调试 | 53 passed |
| 实际脚本：环境＋协议＋类别＋数据 ID | 1 passed |
| 实际脚本：HTTP/WS 多文件＋多个 ID | 2 passed |
| 实际脚本：显式配置文件＋混合流程 | 1 passed |
| pip check | No broken requirements found |
| 中文注释和三引号说明排版 | 29 个 Python 文件检查通过 |
| 旧模块导入、四种调试配置路径 | 检查通过 |
| HDMI/关联流程的实际请求证据 | 发送 10 后恢复 30，恢复检查点存在 |
| HTTP 到 WS 的结果传递 | 流程中实际使用 HTTP 返回的 MAC 发出 WS 登录 |

53 项包含 3 条正式接口/流程用例和 50 项框架回归，不表示增加了 53 条业务协议预期。

## 关键回归

- 同接口两组数据复用一个 HTTP/WS 连接，每组分别恢复原音量；默认 cookie/header 修改不会影响下一组。
- 控制确认与状态推送可乱序，旧回包不能满足新请求，日志和心跳不会被错误消费。
- 拒绝回包、HTTP 4xx/5xx 原样返回给用例；模拟负数、小数仅验证公共层不擅自拦截输入。
- 业务断言失败后恢复；恢复拒绝明确报告并关闭资源。
- 不确定控制后重连，仅原状态一致才允许后续 case；状态已改变时不自动恢复或重发。
- 独立特殊连接关闭不破坏普通共享连接；握手 cookies/headers 与业务凭据脱敏。
- 协议、文件、类别、精确 ID、多 ID、环境冲突、无匹配、旧参数和缺失凭据均验证。

## 可追溯报告

完整报告：[junit.xml](../artifacts/20261016-120048-bd3b4858/junit.xml)。

调试模式：[asyncio-debug.xml](../artifacts/interface-refactor-validation/asyncio-debug.xml)。

多接口：[junit.xml](../artifacts/20261016-120213-2a2bea09/junit.xml)。

验收汇总：[summary.json](../artifacts/interface-refactor-validation/summary.json)。

修改前源码快照：[ZIP](../artifacts/before-interface-refactor-20261016-114629.zip)。原历史报告及早期快照均保留。

## 待确认边界

正式 HDMI 数据仍为音量 10。0、1、99、100、101、-1、1.5 等的真实接受、拒绝、限幅或取整规则未全部确认，本次未据模拟器补造正式预期。

自动账号登录、有效凭据获取、真机物理声音效果、服务器到终端 TCP 行为未验证。当前业务 JSON 登录沿用已采集协议。
