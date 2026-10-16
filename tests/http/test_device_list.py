"""设备列表接口：请求路径、参数和断言都在此处可见。"""

import pytest
from common.data_loader import load_cases

pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.normal]


@pytest.mark.parametrize("case", load_cases("http/device_list.json", "normal"), ids=lambda case: case["id"])
async def test_get_device_list(http, settings, case):
    """验证列表接口成功，并返回唯一、型号正确且在线的目标设备。"""

    response = await http.get("/api/educontrol/lists", params=case["request"]["params"])

    # 验证 HTTP 状态及业务成功字段。
    assert response.status_code == case["expected"]["status_code"]
    body = response.json()
    assert body["result"] == case["expected"]["result"]
    assert body["data"]["status"] == case["expected"]["status"]

    # 验证目标设备，而不是把任意列表记录当成目标。
    devices = body["data"]["data"]["data"]
    target = [device for device in devices if device["mac"].lower() == settings.mac.lower()]
    assert len(target) == 1
    assert target[0]["device_type"] == settings.model
    assert target[0]["online_status"] == case["expected"]["online_status"]
