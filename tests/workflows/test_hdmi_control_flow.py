"""HTTP 上游结果直接传入 WS 请求；一个流程是一条独立测试，不依赖其他测试先运行。"""

import pytest
from common.data_loader import load_cases

pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.normal,
              pytest.mark.workflow, pytest.mark.usefixtures("initial_state")]


@pytest.mark.parametrize("case", load_cases("workflows/hdmi_control_flow.json", "normal"), ids=lambda case: case["id"])
async def test_http_device_to_websocket_control(http, ws, settings, case):
    """HTTP 查找目标 MAC，明确传给 WS 登录，再执行控制和状态验证。"""

    response = await http.get("/api/educontrol/lists", params=case["request"]["list_params"])
    assert response.status_code == case["expected"]["http_status"]
    body = response.json()
    assert body["result"] == case["expected"]["result"]
    assert body["data"]["status"] == "success"
    matches = [item for item in body["data"]["data"]["data"] if item["mac"].lower() == settings.mac.lower()]
    assert len(matches) == 1
    target = matches[0]
    assert target["device_type"] == settings.model and target["online_status"] == 1

    # 将上游 HTTP 返回的 MAC 明确用于下游 WS 请求。
    login = await ws.request({"actioncode": "login", "data": target["mac"]})
    assert login["return"] == case["expected"]["return"]
    response = await ws.request({"actioncode": "execute_HDMI_Audio_Control", "data": case["request"]["volume"]})
    assert response["return"] == case["expected"]["return"]
    assert type(response["data"]) is int and response["data"] == case["expected"]["volume"]

    # 验证推送与主动查询，不把收到回包等同于状态已经正确。
    await ws.wait_for_state({"HDMI_audio_status": case["expected"]["volume"]})
    state = await ws.request({"actioncode": "edudevice_get_state", "data": "get_state"})
    assert state["return"] == 0
    assert type(state["data"]["HDMI_audio_status"]) is int
    assert state["data"]["HDMI_audio_status"] == case["expected"]["volume"]
