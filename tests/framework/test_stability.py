"""用本地模拟环境检查框架的乱序、超时、断线和资源清理行为。
测试中故意触发的业务异常如果被正确识别，测试本身应通过；这些检查不证明真机执行效果。
"""
import asyncio
import json
import httpx
import pytest
from clients.websocket import HistoryExpired, MessageTimeout, SessionClosed
from clients.device import DeviceClient
from support.evidence import redact, safe_url
from mocks.device_server import Behavior

pytestmark = pytest.mark.stability


@pytest.mark.parametrize("state_before_ack", [False, True])
async def test_out_of_order_messages_and_interleaved_logs(device_factory, state_before_ack):
    """验证回包先到、状态先到两种顺序，并确认插入的日志没有丢失。"""
    device = await device_factory(Behavior(state_before_ack=state_before_ack))
    before = await device.query_state()
    state = await device.set_volume(10)
    assert state["HDMI_audio_status"] == 10
    for field, value in before.items():
        if field != "HDMI_audio_status":
            assert state[field] == value
    assert any(m.payload["actioncode"] == "control_latest_log" for m in device.transport.messages)


async def test_stale_success_and_state_cannot_satisfy_new_command(device_factory):
    """先产生一次成功历史，再丢弃新回包；必须超时，不能拿旧回包通过。"""
    device = await device_factory(reply_timeout=0.15)
    await device.set_volume(10)
    device.simulator.behavior.omit_ack = True
    # pytest.raises 表示预期异常，框架正确报超时才算本测试通过。
    with pytest.raises(MessageTimeout, match="execute_HDMI"):
        await device.set_volume(10)
    with pytest.raises(SessionClosed, match="Previous control failed"):
        await device.set_volume(20)
    controls = [r for r in device.simulator.received if r["actioncode"] == "execute_HDMI_Audio_Control"]
    assert len(controls) == 2


async def test_missing_state_times_out_even_when_ack_succeeds(device_factory):
    """有成功回包但没有状态更新时，仍应判为状态等待超时。"""
    device = await device_factory(Behavior(omit_state=True), state_timeout=0.15)
    with pytest.raises(MessageTimeout, match="HDMI state"):
        await device.set_volume(10)


@pytest.mark.parametrize("behavior,expected", [
    (Behavior(reject=True), "rejected"),
    (Behavior(wrong_ack=True), "acknowledgement value mismatch"),
    (Behavior(wrong_query=True), "HDMI_audio_status expected"),
])
async def test_business_failure_is_not_reported_as_success(device_factory, behavior, expected):
    """分别注入拒绝、错误回包值和错误查询值，确认 API 明确失败。"""
    device = await device_factory(behavior)
    with pytest.raises(AssertionError, match=expected):
        await device.set_volume(10)


@pytest.mark.parametrize("behavior", [Behavior(disconnect=True), Behavior(invalid_json=True)])
async def test_disconnect_or_invalid_message_wakes_waiters(device_factory, behavior):
    """连接断开或收到非法 JSON 后，等待者应尽快失败，且控制不能自动重发。"""
    device = await device_factory(behavior, reply_timeout=2)
    with pytest.raises(SessionClosed):
        async with asyncio.timeout(1):
            await device.set_volume(10)
    assert sum(r["actioncode"] == "execute_HDMI_Audio_Control" for r in device.simulator.received) == 1


async def test_wrong_device_blocks_control(device_factory):
    """会话返回另一台设备的 MAC 时，准备阶段就要失败。"""
    with pytest.raises(AssertionError, match="target MAC mismatch"):
        await device_factory(Behavior(wrong_device=True))


async def test_application_heartbeat_and_cleanup(device_factory):
    """确认业务心跳确实发送，关闭后接收任务和心跳任务都已结束。"""
    device = await device_factory(heartbeat_interval=0.02)
    await asyncio.wait_for(device.simulator.heartbeat_seen.wait(), timeout=1)
    await device.close()
    assert device.transport.reader.done()
    assert device.heartbeat.done()
    await device.close()
    with pytest.raises(SessionClosed):
        await device.wait_action("never", device.transport.cursor, 1)


async def test_overlapping_operations_are_serialized(device_factory):
    """同时提交两个操作，验证会话锁使每次控制及查询完整串行执行。"""
    device = await device_factory()
    # 同时提交任务，验证会话操作锁仍让每个控制闭环串行完成。
    results = await asyncio.gather(device.set_volume(10), device.set_volume(20))
    assert [state["HDMI_audio_status"] for state in results] == [10, 20]


async def test_evicted_history_is_not_silently_used(device_factory):
    """缩小缓存并覆盖历史，验证等待者得到明确异常而不是猜测结果。"""
    device = await device_factory(history_limit=2)
    cursor = device.transport.cursor
    await device.query_state()
    await device.query_state()
    await device.query_state()
    with pytest.raises(HistoryExpired):
        await device.wait_action("login", cursor, 1)


async def test_unrelated_audio_change_is_detected(device_factory):
    """模拟设置 HDMI 时附带改变麦克风，验证其他通道不变断言能发现问题。"""
    device = await device_factory(Behavior(change_other_audio=True))
    before = await device.query_state()
    after = await device.set_volume(10)
    with pytest.raises(AssertionError, match="MIC_audio_status"):
        assert after["MIC_audio_status"] == before["MIC_audio_status"], "MIC_audio_status changed"


async def test_credentials_are_absent_from_evidence(device_factory, evidence):
    """确认请求仍可使用模拟凭据，但落盘证据中已经脱敏且每行是有效 JSON。"""
    device = await device_factory()
    await device.set_volume(10)
    text = evidence.path.read_text(encoding="utf-8")
    assert "mock-token" not in text
    assert "mock-sign" not in text
    assert "[REDACTED]" in text
    for line in text.splitlines():
        json.loads(line)


def test_nested_credentials_and_query_are_redacted():
    """验证嵌套数据和 URL 中的凭据脱敏，正常参数仍保留。"""
    assert redact({"items": [{"token": "a", "value": 10}], "sign": "b"}) == {
        "items": [{"token": "[REDACTED]", "value": 10}], "sign": "[REDACTED]"}
    url = safe_url("http://user:password@localhost/test?sign=secret&data=10")
    assert "password" not in url and "secret" not in url and "data=10" in url


@pytest.mark.parametrize("transport_failure", [False, True])
async def test_http_errors_do_not_expose_signed_url(settings, evidence, transport_failure):
    """模拟 HTTP 500 与连接错误，验证抛出的错误文本不泄露签名 URL。"""
    def handler(request):
        """给 HTTP 客户端注入可控错误，不发真实请求。"""
        if transport_failure:
            raise httpx.ConnectError("secret query could be included here", request=request)
        return httpx.Response(500)
    device = DeviceClient(settings, evidence, httpx.MockTransport(handler))
    try:
        with pytest.raises((RuntimeError, AssertionError)) as error:
            await device.list_devices()
        assert "sign=" not in str(error.value)
        assert "secret query" not in str(error.value)
    finally:
        await device.close()
