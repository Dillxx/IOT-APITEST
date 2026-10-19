# 接口自动化测试任务状态

最后更新：2026-10-17。核对基线：Git 提交 `674309f`，本次建档前工作区干净。本次任务记忆建档及本地复验已完成；当前私有管理员输入路径的真实登录/控制与 IDE 断点命中仍未验证。本文件是任务摘要，实际行为以当前代码和可追溯证据为准。

## 使用与更新规则

- 开始或恢复本项目任务时先读本文件，再核对相关代码和证据；用户最新明确要求优先于旧记录。
- 完成关键阶段、需求或方案变化、出现影响后续工作的阻塞时更新；普通细节采用可逆选择，重大歧义再确认。
- 结束前逐项核对完成标准，明确已完成、未完成和未验证。历史报告不代表后续修改已经通过相同验证。
- 不写密码、令牌、客户端密钥或账号文件内容；不复制完整聊天、抓包和流量日志。凭据文件仅记录路径及配置方式。

## 最终目标与工作范围

建立便于逐个接口阅读、维护和调试的 HTTP/WebSocket 自动化项目：环境、独立 API、测试数据、测试业务流程职责清晰；用例只展示操作和验证，前后置由 fixture 负责。

当前业务范围是 HTTP 设备列表、WebSocket HDMI 音量、跨 HTTP/WS 的关联流程，以及支撑它们的登录、通信、筛选、日志和恢复机制。当前正式 HDMI 参数为 `10`。更多接口及边界用例需按真实协议逐步补充，不把测试框架能力等同于全系统业务覆盖。

最近工作重点：通过全局管理员登录获取本次运行共享的认证信息，使用 TS-9260 做单条 HDMI 真机运行/调试。最近一个具体问题是如何单独运行该用例；运行和调试入口见下文。

## 已确认的决定与关键约束

1. 保留 pytest、HTTPX、websockets 和项目 `.venv`（Python 3.12+），不为重构更换依赖体系。
2. API 单独定义 HTTP 方法/路径、WS 指令及请求结构；用例调用 API 展示业务流。API 返回响应，不自动断言业务成功、不拦截待测业务参数、不隐藏等待状态及查询验证。
3. 脚本在 `tests/`、数据在 `data/`，按协议/接口组织。接口可有正常、拒绝、特殊处理等测试函数，每个函数由多组数据参数化为独立子用例。
4. 未确认的负数、小数、越界输入行为不能编成正式成功/拒绝/限幅预期。设备配置中的 0–100 恢复保护范围尚未确认为真实协议边界。
5. 登录、设备核对、原状态记录、逐条恢复和资源关闭放在 fixture/前后置辅助中。当前同接口文件复用 HTTP 客户端及 WS 连接，每条子用例隔离状态；身份切换/断线测试使用独立资源。
6. 支持单条数据、单接口、多接口、协议、类别选择；关联流程放在独立测试内显式按顺序调用并传递结果，不依赖多个测试函数的执行顺序。
7. WS 每连接只有一个接收任务，发送前记录游标、按条件匹配消息，请求串行。状态可能先于应答到达。控制结果不确定时不自动重放；重连须核对设备及原状态，恢复失败须报告且继续关闭资源。缺少服务端请求 ID 时，延迟同类响应的严格关联仍有限制。
8. 账号从忽略跟踪的 `config/accounts.local.toml` 的 `[admin]` 读取，是平台全局管理员，不属于 TS-9260 专用账号。成对的 `IOT_USERNAME`/`IOT_PASSWORD` 可覆盖本地文件；不把一半环境变量与一半文件值混用。不同服务环境分别登录。
9. 不再从 HAR 提取运行凭据。`-AuthHar`、`--auth-har`、`IOT_AUTH_HAR` 已拒绝使用。历史 HAR 仅是协议调查来源，日常运行不依赖它。
10. 真机登录链路：`GET /accessToken` → `POST /api/login/login` → `GET /api/login/login` 验证会话。HTTP 访问凭证与登录会话 token 分开；客户端配置若未显式提供，则从同源公开页面脚本解析，不执行脚本。
11. 每次测试运行登录一次；`auth.token`/`auth.sign` 和 `token` fixture 提供共享运行信息，HTTP/WS 自动携带。独立登录接口测试不覆盖共享认证信息；token 不落盘。
12. 默认本地模拟；真实访问必须显式传 `--live`/`-Live`。当前真机环境为 `ts9260`，目标 TS-9260，MAC `30:3a:ba:15:7b:ce`；服务器 HTTP `http://172.16.48.230`，WS `ws://172.16.48.230:7578/`。其他模型不能直接套用其验证结论。
13. 真机控制串行运行；同设备不启动多个并发测试进程。正常结束须恢复原状态；强行停止调试可能跳过清理。平台响应、设备状态回读、物理声音效果分开记录。
14. 中文 `#` 注释前若为代码须空一行，注释紧邻其解释的后续代码；函数/类用三引号说明，结束后空一行；`with`/`async with` 块内首处说明用三引号，结束后空一行，不使用行尾中文注释。

## 当前实现与文件入口

| 文件/目录 | 当前职责 |
| --- | --- |
| `api/http/authentication.py` | 访问凭证、登录、会话查询的独立 API |
| `api/http/device_list.py` | HTTP 设备列表 API |
| `api/websocket/hdmi.py`、`api/websocket/session.py` | HDMI 及 WS 会话/设备信息 API |
| `tests/http/test_device_list.py` | 设备列表用例 |
| `tests/websocket/test_hdmi_volume.py` | HDMI 音量用例，当前子用例 `hdmi_volume_10` |
| `tests/workflows/test_hdmi_control_flow.py` | 显式展示多接口关联流程 |
| `data/http/`、`data/websocket/`、`data/workflows/` | 各接口/流程的请求及预期数据 |
| `tests/conftest.py` | 共享认证、接口资源、逐条 baseline/恢复及 API fixture |
| `common/authentication.py`、`config/settings.py` | 本地账号/环境读取与登录编排 |
| `common/http_client.py`、`common/websocket_client.py` | 通信、消息匹配、超时及日志 |
| `common/setup.py`、`common/evidence.py` | 前后置设备操作、恢复及脱敏证据 |
| `common/execution.py`、`run-tests.ps1` | pytest 选项、筛选及统一运行入口 |
| `config/environments/`、`config/devices/` | 服务环境与设备配置；`test` 为 TS-9220，`ts9260` 为 TS-9260 |
| `config/accounts.local.toml.example` | 共享管理员配置模板；实际账号文件已被 Git 忽略 |
| `tests/framework/` | 结构、认证、通信故障、生命周期、筛选等框架回归 |
| `.vscode/launch.json` | “调试 HDMI 真机（TS-9260）”为真实单子用例；其他现有配置为本地模拟 |
| `README.md`、`docs/` | 使用、架构、认证、开发与历史验证说明 |

HDMI 主链路：pytest 收集 JSON 参数 → 读取环境 → session 登录取得认证 → module HTTP 客户端 → 核对目标设备 → 建立/登录 WS → 每条记录原状态 → 用例调用设置 API 并断言应答 → 等待状态/查询验证 → fixture 恢复原值 → 关闭连接并落脱敏证据。

## 进度与验证证据

以下历史报告已在本次建档时读取核对，不能代替修改后的真实环境复验。

| 层次 | 实际文件/命令 | 结果及边界 |
| --- | --- | --- |
| 历史本地回归/模拟器 | `artifacts/platform-admin-validation/local.xml` | 74 项、失败 0、错误 0、跳过 0；覆盖全局管理员配置修改后的本地行为，不代表真实账号已登录 |
| 历史本地异步调试检查 | `artifacts/account-context-validation/debug.xml` | 73 项通过；属于更早的认证上下文阶段，不能视为当前 74 项均已通过异步调试检查 |
| 历史真实接口及设备状态回读 | `artifacts/20261016-151348-7439191a/junit.xml`、同目录 `safe-summary.json` | 1 项通过；TS-9260 原音量 15 → 设置 10 → 恢复并回读 15，认证检查有记录。该轮使用此前 HAR 账号输入路径，后已移除；不证明当前私有文件账号路径已真机通过 |
| 当前配置静态检查 | `config/accounts.local.toml`、`git check-ignore config/accounts.local.toml` | 仅核对 `[admin]` 及用户名/密码已配置，确认文件忽略；未输出值，不等于认证成功 |
| 当前 VS Code 配置静态检查 | `.vscode/launch.json`、`tests/websocket/test_hdmi_volume.py` | 真机配置指定准确子用例及 `--env ts9260 --live`；第 14 行请求前暂停时还没有 response，第 17 行为请求后的断言。未实际验证 IDE 断点命中 |
| 本次本地全量回归/模拟器 | 下文命令；`artifacts/task-state-20261017/local.xml`、`artifacts/task-state-20261017/local/selection.json` | 退出码 0，74 passed（47.39 秒）；XML 中失败/错误/跳过均为 0。包含正式业务用例的本地模拟验证，不代表真机通过 |
| 本次真实模式收集检查 | 下文 `--collect-only` 命令；`artifacts/task-state-20261017/live-collection/selection.json` | 退出码 0，准确收集 `test_set_volume_success[hdmi_volume_10]` 共 1 条；只检查配置与选择，不运行 fixture，不认证/控制设备 |
| 本次依赖及文档检查 | `.\.venv\Scripts\python.exe -m pip check`；`git diff --check`；PowerShell `Test-Path`/`ConvertFrom-Json` 核对 | 均退出码 0；依赖无损坏，已跟踪文件差异无空白错误；21 个任务/证据路径存在，单条选择及汇总 JSON 一致 |

本次汇总：`artifacts/task-state-20261017/summary.json`。执行 pytest 前仅在子进程清空 `PYTEST_ADDOPTS`，避免外部附加选项改变所记命令的模式/选择；未修改用户持久环境变量。

未验证：当前 `[admin]` 私有文件输入在真实环境上的完整登录/控制链路；VS Code 实际断点停靠；设备物理声音变化；服务器至终端 TCP 报文；TS-9220 真机行为；所有输入边界。后四项不是本次建档的完成前提。

## 运行和调试入口

全部命令在项目根目录执行，使用项目解释器，不直接运行测试 `.py` 文件。

本地全量回归（不加 `--live`）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --iot-artifacts=artifacts/task-state-20261017/local --junitxml=artifacts/task-state-20261017/local.xml
```

真实单子用例的收集检查（不发送请求）：

```powershell
.\.venv\Scripts\python.exe -m pytest "tests/websocket/test_hdmi_volume.py::test_set_volume_success[hdmi_volume_10]" --env ts9260 --live --collect-only -q --iot-artifacts=artifacts/task-state-20261017/live-collection
```

真实单子用例执行（会设置音量并在结束时恢复；仅在开展真机验证时执行）：

```powershell
.\.venv\Scripts\python.exe -m pytest "tests/websocket/test_hdmi_volume.py::test_set_volume_success[hdmi_volume_10]" --env ts9260 --live -v -s
```

VS Code：选择 `.vscode/launch.json` 中“调试 HDMI 真机（TS-9260）”，F5 启动；F10 执行请求后看 `response`，F11 进入 API，F5 继续至清理结束。普通终端运行不会自动命中 VS Code 断点。

## 完成标准核对

| 标准 | 状态 |
| --- | --- |
| 独立 API、测试业务流及分离数据/环境，fixture 负责前后置 | 已实现；本次 74 项本地回归通过，真实环境边界另列 |
| HTTP/WS 筛选、关联流程、共享连接及独立状态恢复 | 已实现；本次本地回归通过，不等同于各接口的真机覆盖 |
| 全局管理员配置、运行时共享认证，不依赖 HAR | 代码已实现、本地回归通过；当前账号来源的真实登录仍未验证 |
| 真机 HDMI 请求、状态回读及原值恢复 | 历史路径通过；当前私有管理员输入路径待真实复验 |
| 准确的单条运行及真实调试配置 | 已配置，真实模式单条收集通过；实际断点命中未验证 |
| 中文注释格式与凭据保护约定 | 已记录且有架构/脱敏检查；本次无业务源码修改 |
| 建立可持续读取的 TASK_STATE，关联命令/证据并区分验证层次 | 本次已完成；`AGENTS.md` 已增加启动/恢复先读入口，无凭据值 |

本次同时完成：`docs/development.md` 的旧“凭据只从环境变量取得”说明已改为私有全局管理员文件或成对环境变量；业务源码、真实账号文件、设备状态均未改动。

## 未完成事项与下一步

1. 恢复任务时先读取本文件及最新用户要求；若代码已变化，只复核受影响的结论，不机械重复历史真机控制。
2. 继续真实环境调试时，先验证当前 `[admin]` 来源的登录/会话查询，再对明确目标开展单条 HDMI 调试，记录应答、状态与恢复证据。当前没有发现真实认证失败；此项是未执行，不能写成阻塞或通过。
3. 用户在 IDE 启动真机 F5 并命中断点后，再记录实际断点证据；不能凭配置收集成功宣称调试成功。
4. 正常/拒绝/特殊组扩展的具体输入预期、更多接口范围：待确认。不得为了补数量自造设备边界规则。

当前阻塞：无已知实施阻塞。本次只做本地回归和收集检查，未再次发送真实控制；剩余真实/物理验证按上文标明，未把整个自动化项目写成全部完成。
