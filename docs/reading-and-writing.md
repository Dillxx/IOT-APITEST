# 阅读和新增用例

## 最短阅读路线

1. 打开 tests/http 或 tests/websocket 下的目标用例，看 API 调用顺序和断言。
2. 打开 data 中相同协议和接口名的 JSON，看当前输入和预期。
3. 切换环境时看 config/environments 的 TOML。
4. 需要查看具体路径、指令和报文时看 api/http 或 api/websocket。
5. 需要排查前后置时看 tests/conftest.py 和 common/setup.py。
6. 只有排查传输、匹配或超时时才进入 common/http_client.py 或 websocket_client.py。

## 增加同类数据

在现有 JSON 分组中追加 id/request/expected，相同测试函数会为每组数据独立运行。id 在本数据文件内唯一，建议包含接口名，便于跨接口筛选。

## 增加不同验证类型

同接口增加另一个具名函数，标记 `@pytest.mark.rejected` 或 `special`，显式加载对应 JSON 组。不要把所有正常、拒绝、特殊规则塞进一个 if/elif 执行器；没有明确预期的类别不生成空测试。

## HTTP

请求方法和路径在 API 中定义，测试通过 device_api 等对象传入 case 参数。公共地址/headers/cookies/params 来自环境；API 支持透传请求选项。简单断言直接写在测试中，错误状态码也原样返回。

## WebSocket

actioncode 和消息结构在 API 中定义，case 保留原类型的输入并调用 hdmi_api.set_volume 等方法。需要异步状态时明确调用 ws.wait_for_state，需要查询时明确调用 hdmi_api.query_state；断言仍在测试中。不要把任意下一条消息当作回包。

改 HDMI 状态的模块通过 `pytest.mark.usefixtures("initial_state")` 使用准备和恢复，case 可读取 ws.initial_state 检查未改动的通道。每条数据都会恢复，不依赖上一条。

## 编排与调试

tests/workflows 下的一条测试就是完整流程，各步复用相同 API 定义。上游结果保存在局部变量中，断言通过后再传下游。只测下游时，创建依赖数据应放在 fixture，不能依赖另外一个 test 函数。

VS Code F5 使用已配置的四种本地调试入口；也可在测试资源管理器选择单条数据执行/调试。代码前的断点在该行尚未执行时停住。
