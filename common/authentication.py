"""真机启动认证：读取登录输入，申请新接入令牌，登录并提取新会话 Token。"""

from dataclasses import dataclass, field, replace
import re
from urllib.parse import urljoin, urlsplit

import httpx

from api.http.authentication import AccessTokenApi, LoginApi
from common.http_client import HttpClient


class AuthenticationError(RuntimeError):
    """认证失败时仅携带安全原因，不包含密码、Token 或服务端完整正文。"""

    pass


@dataclass(frozen=True)
class LoginInputs:
    """只在本次进程内保存登录输入，repr 不展示敏感值。"""

    username: str = field(repr=False)
    password: str = field(repr=False)


def load_login_inputs(settings):
    """读取配置层已选定的账号密码，不读取历史抓包或旧 Token。"""

    if not settings.login_username or not settings.login_password:
        raise AuthenticationError("Login requires config/accounts.local.toml or IOT_USERNAME/IOT_PASSWORD")
    return LoginInputs(settings.login_username, settings.login_password)


async def get_client_credentials(http, settings):
    """从环境变量或同源公开前端配置读取接入参数，不执行脚本、不保存凭据。"""

    if settings.auth_client_id and settings.auth_client_secret:
        return settings.auth_client_id, settings.auth_client_secret
    if settings.auth_client_id or settings.auth_client_secret:
        raise AuthenticationError("IOT_CLIENT_ID and IOT_CLIENT_SECRET must be provided together")
    origin = urlsplit(settings.http_base_url)
    response = await http.get("/login")
    if response.status_code != 200:
        raise AuthenticationError(f"Login page unavailable: HTTP {response.status_code}")
    scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)', response.text)
    pattern = re.compile(r'client_id\s*:\s*["\']([^"\']+)["\']\s*,\s*secret\s*:\s*["\']([^"\']+)["\']')
    for script in scripts:
        url = urlsplit(urljoin(settings.http_base_url, script))
        if (url.scheme, url.netloc) != (origin.scheme, origin.netloc):
            continue
        if not re.search(r'/app\.[^/]+\.js$', url.path):
            continue
        source = await http.get(url.geturl())
        if source.status_code == 200:
            match = pattern.search(source.text)
            if match:
                return match.group(1), match.group(2)
    raise AuthenticationError("Frontend bootstrap configuration unavailable; set IOT_CLIENT_ID and IOT_CLIENT_SECRET")


def response_object(response, operation):
    """只返回有效 JSON 对象，不把含凭据的完整响应写入异常。"""

    if response.status_code != 200:
        raise AuthenticationError(f"{operation} failed: HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise AuthenticationError(f"{operation} returned invalid JSON") from None
    if not isinstance(body, dict):
        raise AuthenticationError(f"{operation} returned an unexpected JSON type")
    return body


async def authenticate(settings, evidence, transport=None):
    """按真实 API 申请凭据，只登录一次；返回新的设置副本供后续接口复用。"""

    inputs = load_login_inputs(settings)
    headers = {**settings.http_headers, "decisionplatform": settings.auth_platform}
    current = replace(settings, http_headers=headers)
    async with HttpClient(current, evidence, transport) as http:
        """认证请求不携带旧默认 sign，HTTP/WS Token 仅保留在内存中。"""

        http.params = httpx.QueryParams()
        client_id, secret = await get_client_credentials(http, current)
        access_api = AccessTokenApi(http, current.company, current.http_device_name)
        access_body = response_object(await access_api.get_access_token(client_id, secret), "Access token")
        access_data = access_body.get("data", {})
        access_token = access_data.get("access_token") if isinstance(access_data, dict) else None
        if not isinstance(access_token, str) or not access_token:
            raise AuthenticationError("Access token response missing data.access_token")
        http.headers["Authorization"] = "Bearer " + access_token
        if isinstance(access_data.get("token"), str) and access_data["token"]:
            http.headers["token"] = access_data["token"]
        login_api = LoginApi(http, current.company, current.http_device_name)
        login_body = response_object(await login_api.login(inputs.username, inputs.password, access_token), "Account login")
        login_data = login_body.get("data", {})
        token = login_data.get("data") if isinstance(login_data, dict) else None
        if (login_body.get("result") != 200 or not isinstance(login_data, dict)
                or login_data.get("status") != "success" or not isinstance(token, str) or not token):
            raise AuthenticationError("Account login rejected or missing data.data token")
        http.headers["token"] = token
        info = response_object(await login_api.get_login_info(access_token), "Login verification")
        info_data = info.get("data", {})
        identity = info_data.get("data", {}) if isinstance(info_data, dict) else None
        if (info.get("result") != 200 or not isinstance(identity, dict) or identity.get("token") != token):
            raise AuthenticationError("Login verification token mismatch")
        headers.update({"Authorization": "Bearer " + access_token, "token": token})
        cookies = dict(http.cookies.items())
        evidence.record("checkpoint", operation="HTTP login verified", token_source="data.data",
                        http_auth="Bearer plus token header", ws_auth="JSON token")
        return replace(settings, token=token, sign=access_token, http_headers=headers, http_cookies=cookies)
