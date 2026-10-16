# 接口项目结构

```text
config/              环境和设备配置
tests/http/          HTTP 接口的各类具名测试
tests/websocket/     WS 接口的各类具名测试
tests/workflows/     一个函数内按顺序表达跨接口业务流程
tests/framework/     本地模拟的通信和前后置回归
data/                与 http/websocket/workflows 同名对应的数据
common/              HTTP/WS 通信、数据、前后置辅助、日志和运行筛选
mocks/               本地模拟服务
artifacts/           报告、完整流量、源码快照
```

## 可见的业务步骤

HTTP 直接 `await http.get/post(...)`，返回 HTTPX Response；WS 直接 `await ws.request({...})`，返回原始业务字典。公共通信不要求业务一定成功，不拦截接口参数的负数、小数。业务成功/拒绝由 case 断言。

HDMI case 明确展示控制请求、回包断言、状态等待、主动查询、状态及其他通道断言。原 DeviceClient/set_volume 的自动成功闭环不再作为用例入口。

HTTP 支持 headers/cookies/params/json/data；WS 支持配置握手 headers/cookies，当前已采集协议另使用业务 JSON token/sign 登录。不得把 HTTP 握手和业务 login 混为一谈。

## 前后置和复用

tests/conftest.py 提供同接口 module scope 的底层连接及 function scope 的 case 状态。接口和流程异步用例显式使用 module loop_scope，匹配共享后台接收任务的生命周期；框架故障测试使用独立 function loop。

HTTP 客户端默认设置每条恢复；业务数据的创建/清理在相关 fixture 中。HDMI 使用 initial_state fixture 读取原状态并在结束后恢复。查询接口无需凭空增加状态恢复。

WS 连接失效后不重放请求。若有不确定控制，重新登录后必须主动核对设备状态与原基线一致，否则后续子用例准备失败，需要人工检查。登录/退出/断线等特殊测试使用 isolated_http 或 isolated_ws fixture，关闭它们不会破坏普通共享连接。

## 关联流程

一个流程函数显式调用多个接口、断言上游、提取返回值并传给下游。普通 Python 变量就是步骤上下文，不使用全局变量或依赖测试执行顺序。不新建 YAML 流程引擎。

本次真实协议示例是 HTTP 查找目标 MAC → WS 使用该 MAC 登录 → 控制 HDMI → 验证状态。尚未取得创建/删除接口协议，不虚构接口；未来资源创建后应立即登记 fixture 清理，流程结束按依赖反序清理。

## 日志与限制

每接口一份完整流量，带 case ID 和阶段；后台 reader 使用共享证据上下文，避免 ContextVar 无法传到已创建任务的问题。日志中的本地 sequence 不是服务器请求 ID。

同一 WS 连接仅一个 reader。请求使用发送前游标、actioncode 和串行锁匹配，可提供 match 条件适配有请求 ID 的协议。当前缺少服务器请求流水号，迟到旧消息仍有无法唯一关联的边界；不要并发编排同设备的多个控制闭环。

当前只验证报告状态，不是独立物理声音测量。原值安全范围仍是暂定保护配置，不能据此声称服务器边界已确认。
