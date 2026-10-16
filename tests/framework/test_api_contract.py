"""独立 API 层保留实际响应和待测输入，不暗中执行成功闭环。"""

import httpx
import pytest

from api.http.device_list import DeviceListApi
from api.websocket.hdmi import HdmiApi
from common.http_client import HttpClient
from mocks.device_server import Behavior

pytestmark = pytest.mark.stability


@pytest.mark.parametrize("volume", [-1, 1.5, None, 101])
async def test_hdmi_api_returns_rejection_without_prevalidating_input(session_factory, volume):
    """模拟拒绝仅验证 API 行为，不把这些错误码视为真实设备协议预期。"""

    ws = await session_factory(Behavior(reject=True))
    response = await HdmiApi(ws).set_volume(volume=volume)
    assert response["return"] == 1
    assert type(response["data"]) is type(volume)
    assert response["data"] == volume
    assert not ws.control_uncertain


async def test_hdmi_api_does_not_hide_queries_or_assert_business_values(session_factory):
    """错误确认值及查询值均交给 case，设置方法不会额外发状态查询。"""

    ws = await session_factory(Behavior(wrong_ack=True, wrong_query=True))
    api = HdmiApi(ws)
    start = len(ws.simulator.received)
    response = await api.set_volume(volume=10)
    assert response["return"] == 0 and response["data"] == 11
    assert [item["actioncode"] for item in ws.simulator.received[start:]] == ["execute_HDMI_Audio_Control"]

    # 主动查询只在调用 query_state 后发生，API 不自动断言状态应等于 10。
    state = await api.query_state()
    assert state["return"] == 0 and state["data"]["HDMI_audio_status"] == 99
    assert ws.simulator.received[-1]["actioncode"] == "edudevice_get_state"


async def test_http_api_returns_error_response_and_preserves_request_options(settings, evidence):
    """HTTP 错误状态和业务 body 原样返回，可在 API 调用时指定请求参数。"""

    received = []

    def handler(request):
        """模拟服务端拒绝，不依赖外部系统。"""

        received.append(request)
        return httpx.Response(403, json={"result": 403, "message": "mock rejection"})

    async with HttpClient(settings, evidence, httpx.MockTransport(handler)) as http:
        """使用真实 HTTPX 请求和响应类型验证 API 边界。"""

        response = await DeviceListApi(http).get_device_list(
            params={"actioncode": "invalid", "data": "invalid"}, headers={"X-Case": "rejected"},
        )
        assert response.status_code == 403
        assert response.json() == {"result": 403, "message": "mock rejection"}
    assert received[0].url.path == "/api/educontrol/lists"
    assert received[0].url.params["actioncode"] == "invalid"
    assert received[0].headers["X-Case"] == "rejected"
