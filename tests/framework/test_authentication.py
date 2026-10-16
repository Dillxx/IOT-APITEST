"""账号配置、启动登录及共享认证上下文的本地回归。"""

from dataclasses import replace
import json
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
import pytest

from common.authentication import AuthenticationError, authenticate, load_login_inputs
from config.settings import load_settings

pytestmark = pytest.mark.stability


def login_settings(settings, **overrides):
    """模拟凭据只用于本文件，不依赖用户真实账户。"""

    values = {"auth_mode": "login", "login_username": "mock-user", "login_password": "mock-password",
              "auth_client_id": "mock-client", "auth_client_secret": "mock-client-secret"}
    values.update(overrides)
    return replace(settings, **values)


def auth_transport(settings, *, failure=None, discover=False):
    """使用真实 HTTPX 报文格式模拟完整认证链路。"""

    requests = []

    def handler(request):
        """捕获请求以核对先后顺序、Token 传递和失败停止行为。"""

        requests.append(request)
        path = request.url.path
        if discover and path == "/login":
            return httpx.Response(200, text='<script src="https://unrelated.example/app.external.js"></script><script src="/assets/js/app.mock.js"></script>')
        if discover and path == "/assets/js/app.mock.js":
            return httpx.Response(200, text='const config={client_id:"mock-client",secret:"mock-client-secret"};')
        if path == "/accessToken":
            data = json.loads(request.url.params["data"])
            assert data == {"client_id": "mock-client", "secret": "mock-client-secret"}
            return httpx.Response(200, json={"return": 0, "data": {} if failure == "access" else {
                "access_token": "fresh-access-secret", "expires": 3600}})
        if request.method == "POST" and path == "/api/login/login":
            assert request.headers["Authorization"] == "Bearer fresh-access-secret"
            assert not request.url.query
            form = dict(parse_qsl(request.content.decode(), keep_blank_values=True))
            assert form["actioncode"] == "post_login"
            assert form["data[usernum]"] == "mock-user" and form["data[userpassword]"] == "mock-password"
            assert form["sign"] == "fresh-access-secret"
            return httpx.Response(200, headers={"set-cookie": "sessionid=fresh-cookie-secret; Path=/"}, json={
                "result": 403 if failure == "login" else 200,
                "data": {"status": "failed" if failure == "login" else "success", "data": "fresh-session-secret%2Fencoded"}})
        if request.method == "GET" and path == "/api/login/login":
            assert request.headers["token"] == "fresh-session-secret%2Fencoded"
            assert request.url.params["sign"] == "fresh-access-secret"
            return httpx.Response(200, json={"result": 200, "data": {"status": "success", "data": {
                "userinfo": {"number": "mock-user", "display_name": "mock-user"},
                "token": "different-secret" if failure == "verify" else "fresh-session-secret%2Fencoded"}}})
        raise AssertionError("Unexpected authentication endpoint")

    return httpx.MockTransport(handler), requests


async def test_startup_login_refreshes_headers_ws_token_and_cookies(settings, evidence):
    """新登录值分别填入 HTTP 授权头、token 头和 WS 设置，日志不泄露。"""

    current = login_settings(settings, token="stale-ws-token", sign="stale-sign")
    transport, requests = auth_transport(current)
    result = await authenticate(current, evidence, transport)
    assert [request.method for request in requests] == ["GET", "POST", "GET"]
    assert result.sign == "fresh-access-secret"
    assert result.token == "fresh-session-secret%2Fencoded"
    assert result.http_headers["Authorization"] == "Bearer fresh-access-secret"
    assert result.http_headers["token"] == result.token
    assert result.http_cookies["sessionid"] == "fresh-cookie-secret"
    assert current.token == "stale-ws-token"
    text = evidence.path.read_text(encoding="utf-8")
    for secret in ("mock-user", "mock-password", "mock-client-secret", "fresh-access-secret",
                   "fresh-session-secret", "fresh-cookie-secret", "stale-ws-token", "stale-sign"):
        assert secret not in text
        assert secret not in repr(result)


@pytest.mark.parametrize("failure,expected_count,reason", [
    ("access", 1, "data.access_token"),
    ("login", 2, "Account login rejected"),
    ("verify", 3, "token mismatch"),
])
async def test_login_failures_stop_without_retry_or_secret_errors(settings, evidence, failure, expected_count, reason):
    """认证失败不重试密码，不进入下游设备接口。"""

    current = login_settings(settings)
    transport, requests = auth_transport(current, failure=failure)
    with pytest.raises(AuthenticationError, match=reason) as error:
        """错误只能描述失败阶段，不包含完整业务正文。"""

        await authenticate(current, evidence, transport)
    assert len(requests) == expected_count
    assert "mock-password" not in str(error.value) and "fresh-session-secret" not in str(error.value)


async def test_bootstrap_discovers_same_origin_public_config(settings, evidence):
    """没有接入配置时只读取同源主脚本，不向第三方发送请求。"""

    current = login_settings(settings, auth_client_id="", auth_client_secret="")
    transport, requests = auth_transport(current, discover=True)
    result = await authenticate(current, evidence, transport)
    assert result.token == "fresh-session-secret%2Fencoded"
    assert [request.url.path for request in requests[:3]] == ["/login", "/assets/js/app.mock.js", "/accessToken"]
    assert all(request.url.host != "unrelated.example" for request in requests)
    assert "mock-client-secret" not in evidence.path.read_text(encoding="utf-8")


async def test_configured_account_requests_new_token(settings, evidence):
    """只使用配置中的账号密码，每次认证都调用接口取得当前 Token。"""

    current = login_settings(settings)
    transport, _ = auth_transport(current)
    result = await authenticate(current, evidence, transport)
    assert result.token == "fresh-session-secret%2Fencoded"


def test_missing_account_does_not_fall_back_to_other_sources(settings):
    """账号未填写时明确失败，不读取抓包补齐。"""

    with pytest.raises(AuthenticationError, match="config/accounts.local.toml"):
        """缺失输入时不应发起登录请求。"""

        load_login_inputs(login_settings(settings, login_username="", login_password=""))


def private_environment(tmp_path):
    """创建独立的模拟环境和账号表，不接触本机真实私有文件。"""

    root = Path(__file__).resolve().parents[2]
    text = (root / "config/environments/ts9260.toml").read_text(encoding="utf-8")
    text = text.replace("../devices/ts9260.toml", (root / "config/devices/ts9260.toml").as_posix())
    text = text.replace("../accounts.local.toml", "accounts.local.toml")
    environment = tmp_path / "ts9260.toml"
    environment.write_text(text, encoding="utf-8")
    (tmp_path / "accounts.local.toml").write_text(
        '[admin]\nusername="mock-user"\npassword="mock-password"\n[other]\nusername="other"\npassword="other"\n',
        encoding="utf-8",
    )
    return environment


def test_global_admin_account_file_is_loaded(tmp_path, monkeypatch):
    """平台管理员账号独立于设备，私有输入不出现在 Settings 的 repr 中。"""

    monkeypatch.delenv("IOT_USERNAME", raising=False)
    monkeypatch.delenv("IOT_PASSWORD", raising=False)
    current = load_settings(private_environment(tmp_path))
    assert current.login_username == "mock-user" and current.login_password == "mock-password"
    assert "mock-password" not in repr(current)


def test_same_platform_devices_share_default_admin_account(tmp_path, monkeypatch):
    """切换设备和环境文件名不改变默认管理员来源。"""

    monkeypatch.delenv("IOT_USERNAME", raising=False)
    monkeypatch.delenv("IOT_PASSWORD", raising=False)
    first = private_environment(tmp_path)
    root = Path(__file__).resolve().parents[2]
    text = first.read_text(encoding="utf-8").replace('account = "admin"', "")
    text = text.replace((root / "config/devices/ts9260.toml").as_posix(),
                        (root / "config/devices/ts9220.toml").as_posix())
    second = tmp_path / "another_device.toml"
    second.write_text(text, encoding="utf-8")
    one, two = load_settings(first), load_settings(second)
    assert one.mac != two.mac and one.model != two.model
    assert one.login_username == two.login_username == "mock-user"
    assert one.login_password == two.login_password == "mock-password"


def test_environment_account_override_uses_complete_pair(tmp_path, monkeypatch):
    """显式环境变量可覆盖私有配置，两处来源不会被拼成一个账号。"""

    environment = private_environment(tmp_path)
    monkeypatch.setenv("IOT_USERNAME", "override-user")
    monkeypatch.setenv("IOT_PASSWORD", "override-password")
    current = load_settings(environment)
    assert current.login_username == "override-user" and current.login_password == "override-password"
    monkeypatch.delenv("IOT_PASSWORD")
    current = load_settings(environment)
    assert current.login_password == ""
    with pytest.raises(AuthenticationError):
        """不从私有配置借用另一个密码。"""

        load_login_inputs(current)


@pytest.mark.asyncio(loop_scope="module")
async def test_run_scoped_auth_is_shared_by_http_and_ws(auth, token, http, ws):
    """用例可直接取 token，HTTP 与 WS 自动携带同一份共享值。"""

    assert token == auth.token == ws.settings.token
    assert http.headers["token"] == token


def test_form_password_and_json_query_secrets_are_redacted():
    """表单括号字段、JSON 查询参数和 URL 编码字段均脱敏。"""

    from common.evidence import redact, safe_url

    value = redact({"data[userpassword]": "password-secret", "data%5Busernum%5D": "account-secret"})
    assert value == {"data[userpassword]": "[REDACTED]", "data%5Busernum%5D": "[REDACTED]"}
    url = safe_url('http://example.test/accessToken?data={"client_id":"client","secret":"client-secret"}')
    assert "client-secret" not in url
