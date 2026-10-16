"""通用请求的业务拒绝、输入类型、HTTP 参数和环境配置回归。"""

from dataclasses import replace
import json

import httpx
import pytest

from common.data_loader import load_cases
from common.http_client import HttpClient
from config.settings import load_settings
from mocks.device_server import Behavior

pytestmark = pytest.mark.stability


async def test_websocket_rejection_is_returned_to_case(session_factory):
    """拒绝回包原样返回，case 能自行断言错误码。"""

    ws = await session_factory(Behavior(reject=True))
    response = await ws.request({"actioncode": "execute_HDMI_Audio_Control", "data": -1})
    assert response["return"] == 1
    assert response["data"] == -1
    assert not ws.control_uncertain


async def test_websocket_handshake_headers_and_cookies(session_factory, evidence):
    """握手公共字段与业务 JSON 字段分别配置，日志不泄露凭据。"""

    ws = await session_factory(ws_headers={"X-WS": "test", "Authorization": "ws-header-secret"},
                               ws_cookies={"session": "ws-cookie-secret"})
    headers = ws.simulator.socket.request.headers
    assert headers["X-WS"] == "test"
    assert headers["Authorization"] == "ws-header-secret"
    assert "session=ws-cookie-secret" in headers["Cookie"]
    text = evidence.path.read_text(encoding="utf-8")
    assert "ws-header-secret" not in text and "ws-cookie-secret" not in text


@pytest.mark.parametrize("volume", [-1, 101, 1.5])
async def test_websocket_does_not_prevalidate_business_input(session_factory, volume):
    """仅证明模拟请求不被客户端拦截，不代表这些输入的真实业务预期。"""

    ws = await session_factory()
    response = await ws.request({"actioncode": "execute_HDMI_Audio_Control", "data": volume})
    assert response["data"] == volume
    assert any(item["data"] == volume for item in ws.simulator.received
               if item["actioncode"] == "execute_HDMI_Audio_Control")


def test_data_preserves_business_types_and_returns_independent_copies(tmp_path):
    """数据层不把小数转成整数，不限制服务端参数边界。"""

    path = tmp_path / "cases.json"
    inputs = [-1, 101, 1.5, None, True, "invalid"]
    path.write_text(json.dumps({"normal": [{"id": str(i), "request": {"data": value}, "expected": {}}
                                            for i, value in enumerate(inputs)]}), encoding="utf-8")
    first = load_cases(path)
    assert [case["request"]["data"] for case in first] == inputs
    first[0]["request"]["data"] = 999
    assert load_cases(path)[0]["request"]["data"] == -1


def test_duplicate_data_ids_are_rejected(tmp_path):
    """重复 ID 在执行前暴露，确保精确选择子用例的含义明确。"""

    path = tmp_path / "cases.json"
    case = {"id": "same", "request": {}, "expected": {}}
    path.write_text(json.dumps({"normal": [case, case]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        """重复编号不是有效的接口数据集合。"""

        load_cases(path)


async def test_http_request_fields_and_raw_error_response(settings, evidence):
    """原生 headers/cookies/params/json/data 和 4xx 响应可直接使用。"""

    seen = []

    def handler(request):
        """本地检查请求实际到达传输器的内容。"""

        seen.append(request)
        return httpx.Response(422, json={"code": "invalid", "token": "response-secret"})

    current = replace(settings, http_headers={"X-Env": "test"}, http_cookies={"session": "cookie-secret"})
    async with HttpClient(current, evidence, httpx.MockTransport(handler)) as http:
        """用例自己判断错误响应是否符合预期。"""

        response = await http.post("/example", headers={"X-Case": "json"}, params={"page": 1},
                                   json={"value": 1.5, "token": "body-secret"})
        assert response.status_code == 422 and response.json()["code"] == "invalid"
        await http.post("/example", data={"value": "10", "password": "form-secret"})
    assert seen[0].headers["X-Env"] == "test" and seen[0].headers["X-Case"] == "json"
    assert "cookie-secret" in seen[0].headers["cookie"]
    assert seen[0].url.params["page"] == "1"
    assert json.loads(seen[0].content)["value"] == 1.5
    assert b"value=10" in seen[1].content
    text = evidence.path.read_text(encoding="utf-8")
    assert all(secret not in text for secret in ("cookie-secret", "body-secret", "form-secret", "response-secret"))


def test_environment_headers_cookies_and_params_are_loaded(tmp_path, monkeypatch):
    """环境公共配置和运行时凭据来源均可验证，不执行登录网络请求。"""

    device = tmp_path / "device.toml"
    device.write_text('[device]\nmac="test"\nmodel="test"\nname="test"\n[capabilities]\nhdmi_volume=true\n[hdmi]\nmin=0\nmax=100\n', encoding="utf-8")
    env = tmp_path / "env.toml"
    env.write_text('''[server]
http_base_url="http://example.test"
ws_url="ws://example.test"
[device]
config_file="device.toml"
[protocol]
[timeouts]
connect=1
http=1
reply=1
state=1
heartbeat_interval=1
history_limit=20
[execution]
restore_original=true
[http.headers]
Accept="application/json"
[http.params]
tenant="test"
''', encoding="utf-8")
    monkeypatch.setenv("IOT_HTTP_HEADERS", '{"Authorization":"runtime-secret"}')
    monkeypatch.setenv("IOT_HTTP_COOKIES", '{"session":"runtime-cookie"}')
    current = load_settings(env)
    assert current.http_headers["Accept"] == "application/json"
    assert current.http_headers["Authorization"] == "runtime-secret"
    assert current.http_cookies["session"] == "runtime-cookie"
    assert current.http_params["tenant"] == "test"


@pytest.mark.asyncio(loop_scope="module")
async def test_isolated_connections_can_be_closed_without_affecting_shared_ws(ws, isolated_ws):
    """特殊会话退出不影响同接口的普通共享连接。"""

    assert ws is not isolated_ws
    await isolated_ws.close()
    assert isolated_ws.reader.done() and isolated_ws.heartbeat.done()
    response = await ws.request({"actioncode": "edudevice_get_state", "data": "get_state"})
    assert response["return"] == 0
