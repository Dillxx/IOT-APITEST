# API 定义

http 中定义 HTTP 方法、路径和请求参数传递；websocket 中定义业务指令和消息结构。

- DeviceListApi.get_device_list：设备列表请求，返回 HTTPX Response。
- HdmiApi.set_volume / query_state：分别发送控制和查询，返回实际业务字典。
- SessionApi.login / get_device_info：业务登录和设备信息请求。

API 不断言业务成功，不检查目标音量是否合法，不自动等待状态或主动查询。接口调用顺序、状态等待和断言由用例展示；连接、登录准备、恢复和关闭由 fixture 管理。
