"""保留原有通信故障回归；成功/拒绝由测试断言，不再依赖设备业务方法。"""

import asyncio
import json

import httpx
import pytest

from common.evidence import redact, safe_url
from common.http_client import HttpClient
from common.setup import read_state
from common.websocket_client import HistoryExpired, MessageTimeout, SessionClosed
from mocks.device_server import Behavior

pytestmark = pytest.mark.stability


async def check_control(ws, volume):
    """仅供故障回归复用断言，正式接口脚本中完整展示相同验证。"""

    response = await ws.request({"actioncode": "execute_HDMI_Audio_Control", "data": volume})
    assert response["return"] == 0, "Control rejected"
    assert type(response["data"]) is int and response["data"] == volume, "acknowledgement value mismatch"
    await ws.wait_for_state({"HDMI_audio_status": volume})
    state = await read_state(ws)
    assert type(state.get("HDMI_audio_status")) is int and state["HDMI_audio_status"] == volume, "HDMI_audio_status expected target"
    return state


@pytest.mark.parametrize("state_before_ack", [False, True])
async def test_out_of_order_messages_and_interleaved_logs(session_factory, state_before_ack):
    """允许状态在确认前到达，保留插入的日志和心跳。"""

    ws = await session_factory(Behavior(state_before_ack=state_before_ack))
    before = await read_state(ws)
    state = await check_control(ws, 10)
    for field, value in before.items():
        if field != "HDMI_audio_status":
            assert state[field] == value
    assert any(message.payload["actioncode"] == "control_latest_log" for message in ws.messages)


async def test_stale_success_and_state_cannot_satisfy_new_command(session_factory):
    """旧成功回包不能满足新请求，超时后禁止再次发送控制。"""

    ws = await session_factory(reply_timeout=0.15)
    await check_control(ws, 10)
    ws.simulator.behavior.omit_ack = True
    with pytest.raises(MessageTimeout, match="execute_HDMI"):
        """本次必须等待新回包并失败。"""

        await ws.request({"actioncode": "execute_HDMI_Audio_Control", "data": 10})
    with pytest.raises(SessionClosed, match="Previous control failed"):
        """不自动重放，也不继续下一次控制。"""

        await ws.request({"actioncode": "execute_HDMI_Audio_Control", "data": 20})
    assert sum(item["actioncode"] == "execute_HDMI_Audio_Control" for item in ws.simulator.received) == 2


async def test_missing_state_times_out_even_when_ack_succeeds(session_factory):
    """确认回包不能代替目标状态。"""

    ws = await session_factory(Behavior(omit_state=True), state_timeout=0.15)
    with pytest.raises(MessageTimeout, match="HDMI state"):
        """没有状态推送时不能让完整验证通过。"""

        await check_control(ws, 10)


@pytest.mark.parametrize("behavior,expected", [
    (Behavior(reject=True), "rejected"),
    (Behavior(wrong_ack=True), "acknowledgement value mismatch"),
    (Behavior(wrong_query=True), "HDMI_audio_status expected"),
])
async def test_business_failure_is_not_reported_as_success(session_factory, behavior, expected):
    """拒绝、错误回包值、错误查询值分别由相应断言发现。"""

    ws = await session_factory(behavior)
    with pytest.raises(AssertionError, match=expected):
        """公共 request 不代替本测试判断业务成功。"""

        await check_control(ws, 10)


@pytest.mark.parametrize("behavior", [Behavior(disconnect=True), Behavior(invalid_json=True)])
async def test_disconnect_or_invalid_message_wakes_waiters(session_factory, behavior):
    """断线和非法消息立即唤醒等待者，控制只发送一次。"""

    ws = await session_factory(behavior, reply_timeout=2)
    with pytest.raises(SessionClosed):
        """等待者应在业务超时前得知连接已经失效。"""

        async with asyncio.timeout(1):
            """限定测试耗时，不用固定休眠判断结果。"""

            await ws.request({"actioncode": "execute_HDMI_Audio_Control", "data": 10})
    assert sum(item["actioncode"] == "execute_HDMI_Audio_Control" for item in ws.simulator.received) == 1


async def test_wrong_device_blocks_control(session_factory):
    """登录核对目标失败，不能执行用例。"""

    with pytest.raises(AssertionError, match="target MAC mismatch"):
        """错误设备在准备阶段被发现。"""

        await session_factory(Behavior(wrong_device=True))


async def test_application_heartbeat_and_cleanup(session_factory):
    """关闭后 reader 和业务心跳均结束，重复关闭无副作用。"""

    ws = await session_factory(heartbeat_interval=0.02)
    await asyncio.wait_for(ws.simulator.heartbeat_seen.wait(), timeout=1)
    await ws.close()
    assert ws.reader.done() and ws.heartbeat.done()
    await ws.close()
    with pytest.raises(SessionClosed):
        """关闭连接后不可继续等待正常结果。"""

        await ws.wait(lambda body: False, ws.cursor, 1, "never")


async def test_overlapping_requests_are_serialized(session_factory):
    """同连接两个请求完整等待各自确认，不争抢 recv。"""

    ws = await session_factory()
    results = await asyncio.gather(
        ws.request({"actioncode": "execute_HDMI_Audio_Control", "data": 10}),
        ws.request({"actioncode": "execute_HDMI_Audio_Control", "data": 20}),
    )
    assert [response["data"] for response in results] == [10, 20]


async def test_evicted_history_is_not_silently_used(session_factory):
    """缓存淘汰后明确失败，不使用不完整的消息历史。"""

    ws = await session_factory(history_limit=2)
    cursor = ws.cursor
    for _ in range(3):
        await read_state(ws)
    with pytest.raises(HistoryExpired):
        """旧游标超出保留范围时不能猜测关联结果。"""

        await ws.wait(lambda body: body.get("actioncode") == "login", cursor, 1, "login")


async def test_unrelated_audio_change_is_detected(session_factory):
    """其他通道被改变时，用例的直接断言能发现问题。"""

    ws = await session_factory(Behavior(change_other_audio=True))
    before = await read_state(ws)
    after = await check_control(ws, 10)
    with pytest.raises(AssertionError, match="MIC_audio_status"):
        """确认原有通道不变的检查仍有效。"""

        assert after["MIC_audio_status"] == before["MIC_audio_status"], "MIC_audio_status changed"


async def test_credentials_are_absent_from_evidence(session_factory, evidence):
    """每行日志有效且 token/sign 不以明文落盘。"""

    ws = await session_factory()
    await check_control(ws, 10)
    text = evidence.path.read_text(encoding="utf-8")
    assert "mock-token" not in text and "mock-sign" not in text
    assert "[REDACTED]" in text
    for line in text.splitlines():
        json.loads(line)


def test_nested_credentials_and_query_are_redacted():
    """嵌套凭据和签名 URL 脱敏，普通字段保留。"""

    assert redact({"items": [{"token": "a", "value": 10}], "sign": "b"}) == {
        "items": [{"token": "[REDACTED]", "value": 10}], "sign": "[REDACTED]"}
    url = safe_url("http://user:password@localhost/test?sign=secret&data=10")
    assert "password" not in url and "secret" not in url and "data=10" in url


@pytest.mark.parametrize("transport_failure", [False, True])
async def test_http_errors_do_not_expose_signed_url(settings, evidence, transport_failure):
    """HTTP 500 原样返回，传输异常文本不泄露完整签名 URL。"""

    def handler(request):
        """本地注入响应和错误，不发出外部请求。"""

        if transport_failure:
            raise httpx.ConnectError("secret query could be included here", request=request)
        return httpx.Response(500, json={"error": "server failure"})

    async with HttpClient(settings, evidence, httpx.MockTransport(handler)) as http:
        """测试结束仍关闭 HTTPX 连接池。"""

        if transport_failure:
            with pytest.raises(RuntimeError) as error:
                """捕获安全的传输错误信息。"""

                await http.get("/test")
            assert "sign=" not in str(error.value) and "secret query" not in str(error.value)
        else:
            response = await http.get("/test")
            assert response.status_code == 500
