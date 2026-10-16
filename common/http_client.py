"""可直接 get/post 的 HTTPX 客户端；只处理传输和日志，不替用例断言业务。"""

import json
from urllib.parse import parse_qsl

import httpx
from common.evidence import safe_url


class HttpClient(httpx.AsyncClient):
    """复用 HTTPX 原生请求参数和响应对象，包括 headers/cookies/params/json/data。"""

    def __init__(self, settings, evidence, transport=None):
        """环境配置作为默认值，每次请求仍可显式覆盖。"""

        self.evidence = evidence
        super().__init__(
            base_url=settings.http_base_url, timeout=settings.http_timeout,
            headers=settings.http_headers, cookies=settings.http_cookies,
            params={"company": settings.company, "device_name": settings.http_device_name,
                    "sign": settings.sign, **settings.http_params},
            transport=transport, trust_env=False,
        )

    async def send(self, request, **kwargs):
        """保留 4xx/5xx 响应供测试断言，传输异常使用不含凭据的错误文本。"""

        body = None
        try:
            content = request.content
            if content:
                if "json" in request.headers.get("content-type", ""):
                    body = json.loads(content)
                elif "application/x-www-form-urlencoded" in request.headers.get("content-type", ""):
                    body = dict(parse_qsl(content.decode()))
                else:
                    body = {"byte_length": len(content)}
        except (httpx.RequestNotRead, ValueError, UnicodeDecodeError):
            body = "<unparsed body>"
        self.evidence.record("http_request", method=request.method, url=safe_url(str(request.url)),
                             headers=dict(request.headers), body=body)
        try:
            response = await super().send(request, **kwargs)
        except httpx.HTTPError:
            self.evidence.record("failure", reason="HTTP transport failure")
            raise RuntimeError("HTTP transport failure; inspect redacted evidence") from None
        self.evidence.record("http_response", status=response.status_code,
                             url=safe_url(str(response.url)), headers=dict(response.headers))
        try:
            body = response.json()
            if request.url.path == "/api/login/login" and isinstance(body, dict):
                data = body.get("data")
                if isinstance(data, dict):
                    content = data.get("data")
                    if request.method == "POST" and isinstance(content, str):
                        body = {**body, "data": {**data, "data": "[REDACTED]"}}
                    elif isinstance(content, dict) and "userinfo" in content:
                        body = {**body, "data": {**data, "data": {**content, "userinfo": "[REDACTED]"}}}
            self.evidence.record("http_body", body=body)
        except (ValueError, httpx.ResponseNotRead):
            self.evidence.record("http_body", body="<non-JSON or streaming body>")
        return response

    async def aclose(self):
        """关闭连接池，记录接口共享客户端的生命周期。"""

        if not self.is_closed:
            await super().aclose()
            self.evidence.record("http_close")
