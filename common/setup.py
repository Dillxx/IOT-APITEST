"""前后置专用辅助：设备核对、状态读取和恢复，不作为测试的业务转发层。"""

import json


async def verify_device(http, settings):
    """通过真实列表报文检查唯一 MAC、型号和在线状态，返回目标记录。"""

    response = await http.get("/api/educontrol/lists", params={
        "actioncode": "get_lists",
        "data": json.dumps({"status": 0, "is_page": 0}, separators=(",", ":")),
    })
    assert response.status_code == 200, f"Device list HTTP status: {response.status_code}"
    body = response.json()
    assert body.get("result") == 200 and body.get("data", {}).get("status") == "success", "Device list rejected"
    records = body["data"]["data"]["data"]
    matches = [item for item in records if item.get("mac", "").lower() == settings.mac.lower()]
    assert len(matches) == 1, "Target MAC must identify exactly one device"
    device = matches[0]
    assert device.get("device_type") == settings.model, "Target device model mismatch"
    assert device.get("online_status") == 1, "Target device is not online"
    return device


async def read_state(ws):
    """前后置读取设备原状态；用例中的主动查询仍直接写请求。"""

    response = await ws.request({"actioncode": "edudevice_get_state", "data": "get_state"},
                                timeout=ws.settings.state_timeout)
    assert response.get("return") == 0, "State query rejected"
    state = response.get("data")
    assert isinstance(state, dict) and "HDMI_audio_status" in state, "State query missing HDMI_audio_status"
    return state


async def restore_hdmi(ws, original):
    """只恢复前置记录的安全原值；控制结果不确定时不自动重发。"""

    try:
        state = await read_state(ws)
        if state["HDMI_audio_status"] != original:
            response = await ws.request({"actioncode": "execute_HDMI_Audio_Control", "data": original})
            assert response.get("return") == 0, "HDMI restore rejected"
            assert type(response.get("data")) is int and response["data"] == original, "HDMI restore acknowledgement mismatch"
            await ws.wait_for_state({"HDMI_audio_status": original})
            state = await read_state(ws)
        assert type(state.get("HDMI_audio_status")) is int and state["HDMI_audio_status"] == original, "Original HDMI volume was not restored"
        ws.evidence.record("checkpoint", operation="original HDMI volume restored", value=original)
    except BaseException:
        ws.evidence.record("restore_failed", original_volume=original,
                           instruction="Check terminal state manually; no automatic command replay")
        raise
