# 云控接口自动化：环境＋API＋用例＋数据

API 单独定义 HTTP/WS 请求；用例调用 API 展示业务步骤并断言响应。环境、数据和前后置各自维护。默认本地模拟，实际设备必须显式 `-Live`。

## 日常维护入口

| 要做的事 | 位置 |
|---|---|
| 选择环境、设备和公共设置 | config/environments、config/devices |
| 定义 HTTP 路径、WS 指令和请求结构 | api/http、api/websocket |
| 编写业务流和断言 | tests/http、tests/websocket、tests/workflows |
| 增加某接口的输入和预期 | data/http、data/websocket |

先看 [HDMI API](api/websocket/hdmi.py)，再看 [HDMI 脚本](tests/websocket/test_hdmi_volume.py) 和 [对应数据](data/websocket/hdmi_volume.json)。HTTP 示例是 [设备列表](tests/http/test_device_list.py)，关联流程在 [workflows](tests/workflows/test_hdmi_control_flow.py)。

## 运行

在项目根目录执行，不需要激活虚拟环境：

```powershell
# 全部测试
.\run-tests.ps1

# 单协议、单接口、多接口
.\run-tests.ps1 -Protocol http
.\run-tests.ps1 -Protocol websocket
.\run-tests.ps1 -TestPath tests/websocket/test_hdmi_volume.py
.\run-tests.ps1 -TestPath @('tests/http/test_device_list.py', 'tests/websocket/test_hdmi_volume.py')

# 类别、单条或多条数据、关联流程
.\run-tests.ps1 -Category normal
.\run-tests.ps1 -CaseId hdmi_volume_10
.\run-tests.ps1 -CaseId @('device_list_online', 'hdmi_volume_10')
.\run-tests.ps1 -TestPath tests/workflows

# 环境名对应 config/environments/<名称>.toml
.\run-tests.ps1 -Env test
```

也可以直接使用 pytest，例如：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/websocket/test_hdmi_volume.py -v
.\.venv\Scripts\python.exe -m pytest --protocol http --category normal -v
.\.venv\Scripts\python.exe -m pytest --case-id hdmi_volume_10 -v
```

筛选条件取交集。数据 ID 精确匹配；无匹配或某个 ID 不存在时明确报错。`-Protocol` 只选独立接口，混合流程通过 `-TestPath tests/workflows` 选择。

Windows 若禁止执行脚本，可使用仅对当前命令生效的方式，不需要修改系统策略：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run-tests.ps1 -Protocol websocket
```

## 测试数据

每个接口测试文件有对应 JSON，按 `normal`、`rejected`、`special` 等类别分组。每类写一个具名测试函数，再通过 `@pytest.mark.parametrize` 显式加载该组数据。每条记录包含唯一 id、request 和 expected。

当前正式 HDMI 数据只有音量 10。0、1、99、100、101、-1、1.5 的业务预期尚未全部确认；不把模拟器的接受行为当作真实协议边界。框架测试会在模拟器中验证负数、小数不被客户端提前拦截。

不再使用 `-Data`、`--iot-data` 或 `IOT_HDMI_VOLUME` 静默修改用例。修改对应 JSON 后按 ID 选择。旧入口会明确提示迁移。

## 连接和前后置

同一接口文件复用 HTTP 客户端和 WS 连接；HTTP 的默认 headers/cookies/params 修改按 case 还原。HDMI 每条数据单独读取初始音量、执行、恢复。前后置在 tests/conftest.py；用例中不展示连接或恢复步骤。

登录失败、断线等特殊场景使用 tests/framework 的独立本地资源。控制结果不确定时不重发；后续必须重新建立连接、核对目标及原状态一致，否则停止控制并报告。恢复失败显示 teardown error，资源清理继续执行。

## 环境与凭据

`-Env test` 使用 config/environments/test.toml；`-Config` 可指定 TOML 文件，两者不能同时使用。新增环境复制 TOML 并调整地址、设备引用和公共设置即可。

HTTP 默认公共查询字段为 company/device_name/sign，来自已采集协议。可在 `[http.headers]` 和 `[http.params]` 中增加非敏感公共设置。HTTP cookies 和敏感 headers 通过 JSON 环境变量 `IOT_HTTP_COOKIES`、`IOT_HTTP_HEADERS` 提供。WS 握手支持 `[websocket.headers]`、`IOT_WS_HEADERS` 和 `IOT_WS_COOKIES`；这些与业务 JSON token/sign 分开。WS 业务公共字段从环境设置补齐，case 显式字段优先。

实际设备仍需有效 `IOT_TOKEN` 和 `IOT_SIGN`，可另设 `IOT_WS_SIGN`，并显式 `-Live`。当前不包含自动账号登录/凭据获取。真机禁止 xdist 并行，不要启动多个进程控制同一终端。

## 报告与调试

artifacts/<运行编号>/ 中包含 junit.xml、selection.json 及按接口路径组织的 traffic.jsonl。日志记录请求、响应、后台推送、case ID 和 setup/test/teardown 阶段，并脱敏凭据。连接级事件没有 case ID 属正常情况。

VS Code 按 Ctrl+Shift+D，选择“调试 HDMI 接口（本地模拟）”“调试 HTTP 接口（本地模拟）”“调试关联流程（本地模拟）”或“调试当前接口文件（本地模拟）”，按 F5。断点行执行前暂停，查看 response 时应停在请求之后。

结构与写法见 [architecture.md](docs/architecture.md)、[reading-and-writing.md](docs/reading-and-writing.md)；验收见 [validation.md](docs/validation.md)。
