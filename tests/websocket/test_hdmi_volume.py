"""HDMI 音量接口：控制、回包、状态等待和主动查询全部显式展示。"""

import pytest
from common.data_loader import load_cases

pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.normal,
              pytest.mark.usefixtures("initial_state")]


@pytest.mark.parametrize("case", load_cases("websocket/hdmi_volume.json", "normal"), ids=lambda case: case["id"])
async def test_set_volume_success(hdmi_api, ws, case):
    """多组正常数据复用相同操作与断言，每条都有独立准备和恢复。"""

    response = await hdmi_api.set_volume(volume=case["request"]["data"])

    # 验证控制回包，不由公共请求方法替用例判断业务成功。
    assert response["return"] == case["expected"]["return"]
    assert type(response["data"]) is int
    assert response["data"] == case["expected"]["data"]

    # 等待状态推送，再发起一次主动查询复核。
    await ws.wait_for_state(case["expected"]["state"])
    state_response = await hdmi_api.query_state()
    assert state_response["return"] == 0
    state = state_response["data"]
    assert type(state["HDMI_audio_status"]) is int
    assert state["HDMI_audio_status"] == case["expected"]["state"]["HDMI_audio_status"]

    # 验证其他原本存在的音频通道未改变。
    if case["expected"]["other_audio_unchanged"]:
        for field in ("IP_broadcast_audio_status", "MIC_audio_status", "iHub_audio_status",
                      "Recorder_audio_status", "Desktop_mike_audio_status"):
            if field in ws.initial_state:
                assert state.get(field) == ws.initial_state[field], f"Unrelated audio changed: {field}"
