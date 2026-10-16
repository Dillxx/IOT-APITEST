"""音频前后置：记录初始状态，测试结束后恢复音量；不占用全局 conftest。"""
import pytest


@pytest.fixture
async def hdmi_device(request, device_factory):
    """提供已登录的设备及 initial_state，结束后尝试恢复原音量。
    清理在 finally 中执行；恢复失败不会被吞掉，会显示为 teardown 错误。
    """
    device = await device_factory(live=request.config.getoption("--live"))
    before = await device.query_state()
    # 恢复目标来自操作前查询，不是测试数据中的目标音量。
    original = before["HDMI_audio_status"]
    if type(original) is not int or not device.settings.hdmi_min <= original <= device.settings.hdmi_max:
        pytest.fail("Cannot safely restore the original HDMI volume; original value invalid")
    device.evidence.record("checkpoint", operation="baseline", state=before)
    try:
        # 用例在这里取得对象并执行，成功或失败都会继续进入 finally。
        device.initial_state = before
        yield device
    finally:
        if device.settings.restore_original:
            try:
                current = await device.query_state()
                if current["HDMI_audio_status"] != original:
                    # 原值不同且会话允许控制时才发送恢复；未知结果不会被自动重放。
                    current = await device.set_volume(original)
                actual = current.get("HDMI_audio_status")
                assert type(actual) is int and actual == original, "Original HDMI volume was not restored"
                device.evidence.record("checkpoint", operation="original HDMI volume restored", value=original)
            except Exception:
                # 记录恢复失败并重新抛出，pytest 会显示清理阶段错误。
                device.evidence.record("restore_failed", original_volume=original,
                                       instruction="Check terminal state manually; no automatic command replay")
                raise
