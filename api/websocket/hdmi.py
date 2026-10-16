"""HDMI 控制及其使用的状态查询接口，不自动执行验证闭环。"""


class HdmiApi:
    """每个方法只发送对应请求，返回原始业务回包。"""

    def __init__(self, ws):
        """复用前置提供的已登录 WebSocket 连接。"""

        self.ws = ws

    async def set_volume(self, volume, **request_options):
        """发送设置音量请求，负数、小数、空值等测试输入不在本层拦截。"""

        return await self.ws.request(
            {"actioncode": "execute_HDMI_Audio_Control", "data": volume},
            **request_options,
        )

    async def query_state(self, **request_options):
        """发送设备状态查询；不会替用例检查成功码或状态值。"""

        return await self.ws.request(
            {"actioncode": "edudevice_get_state", "data": "get_state"},
            **request_options,
        )
