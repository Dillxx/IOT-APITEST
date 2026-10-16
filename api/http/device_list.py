"""设备列表 HTTP 接口定义。"""


class DeviceListApi:
    """复用已准备的 HTTP 客户端，返回完整 HTTPX 响应。"""

    def __init__(self, http):
        """连接、环境和登录由前后置提供。"""

        self.http = http

    async def get_device_list(self, params, **request_options):
        """调用设备列表接口；参数原样传递，headers/cookies/timeout 等可显式指定。"""

        return await self.http.get(
            "/api/educontrol/lists",
            params=params,
            **request_options,
        )
