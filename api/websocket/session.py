"""业务登录和设备信息接口，与 WebSocket 标准握手分开。"""


class SessionApi:
    """提供可在前置或关联流程中单独调用的业务会话接口。"""

    def __init__(self, ws):
        """接收已建立的 WebSocket 连接。"""

        self.ws = ws

    async def login(self, mac, **request_options):
        """使用上游或环境提供的 MAC 登录，返回实际回包。"""

        return await self.ws.request(
            {"actioncode": "login", "data": mac},
            **request_options,
        )

    async def get_device_info(self, **request_options):
        """查询业务连接的设备信息，不在接口方法中核对目标。"""

        return await self.ws.request(
            {"actioncode": "push_control_info", "data": ""},
            **request_options,
        )
