"""通用 HTTP JSON 客户端。
只负责请求发送、HTTP 错误和证据记录；具体端点、业务成功码与设备检查由 DeviceClient 承担。
"""
import httpx
from support.evidence import Evidence, safe_url


class HttpClient:
    """可复用的异步 HTTP 客户端，封装连接池、JSON 读取和安全错误文本。"""
    def __init__(self, base_url: str, timeout: float, evidence: Evidence, transport=None):
        """创建客户端；transport 可注入 MockTransport，让本地测试不访问真实服务器。"""
        self.evidence = evidence
        self.client = httpx.AsyncClient(
            base_url=base_url, timeout=timeout,
            transport=transport, trust_env=False,
        )

    async def request_json(self, method: str, path: str, *, params=None) -> dict:
        """发送一次请求，确认 HTTP 成功并返回字典类型 JSON。
        method/path/params 由设备操作提供；业务成功码由 DeviceClient 解析。
        """
        request = self.client.build_request(method, path, params=params)
        self.evidence.record("http_request", method=method, url=safe_url(str(request.url)), params=params)
        try:
            response = await self.client.send(request)
        # 库异常可能包含完整签名 URL；统一改为安全错误文本。
        except httpx.HTTPError:
            self.evidence.record("failure", reason="HTTP transport failure")
            raise RuntimeError("HTTP transport failure; inspect redacted evidence") from None
        self.evidence.record("http_response", status=response.status_code,
                             url=safe_url(str(response.url)))
        # 这里只检查 HTTP 状态；业务 result/status 字段由 DeviceClient 检查。
        if not response.is_success:
            raise AssertionError(f"HTTP request failed: status={response.status_code}")
        try:
            body = response.json()
        except ValueError:
            raise AssertionError("HTTP response is not valid JSON") from None
        self.evidence.record("http_body", body=body)
        if not isinstance(body, dict):
            raise AssertionError("HTTP response must be a JSON object")
        return body

    async def close(self):
        """释放 HTTP 连接池，测试清理阶段必须调用。"""
        await self.client.aclose()
