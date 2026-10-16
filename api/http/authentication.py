"""HTTP 接入令牌、账户登录和登录信息接口定义，不在 API 层断言成功。"""

import json


class AccessTokenApi:
    """按当前云控前端协议申请 HTTP Bearer 接入令牌。"""

    def __init__(self, http, company, device_name):
        """公共标识由所选环境提供。"""

        self.http = http
        self.company = company
        self.device_name = device_name

    async def get_access_token(self, client_id, secret):
        """返回原始 HTTP 响应；凭据仅通过本次请求发送。"""

        return await self.http.get("/accessToken", params={
            "company": self.company, "device_name": self.device_name,
            "data": json.dumps({"client_id": client_id, "secret": secret}, separators=(",", ":")),
        })


class LoginApi:
    """表单登录取得 data.data，随后 HTTP token 请求头与 WS token 共用此值。"""

    def __init__(self, http, company, device_name):
        """只保存客户端和公共标识，不持久化账户密码或 Token。"""

        self.http = http
        self.company = company
        self.device_name = device_name

    async def login(self, usernum, userpassword, sign):
        """按 HAR 中的表单字段发送账户登录请求。"""

        return await self.http.post("/api/login/login", data={
            "company": self.company, "device_name": self.device_name,
            "sign": sign, "actioncode": "post_login",
            "data[usernum]": usernum, "data[userpassword]": userpassword,
        })

    async def get_login_info(self, sign):
        """读取登录上下文，返回实际响应供前置核对。"""

        return await self.http.get("/api/login/login", params={
            "company": self.company, "device_name": self.device_name,
            "sign": sign, "actioncode": "get_login", "data": "{}",
        })
