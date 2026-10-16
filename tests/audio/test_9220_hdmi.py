"""HDMI 音量测试：只保留操作和验证，前后置见同目录 conftest.py。"""
import pytest
from support.data import load_hdmi_cases


def pytest_generate_tests(metafunc):
    """本文件的数据来源：--iot-data 指定 JSON，每条 cases 记录运行一次。
    在这里绑定数据是为了保留命令行选文件能力，不再藏到全局 conftest。
    """
    if "hdmi_case" not in metafunc.fixturenames:
        return
    try:
        cases = load_hdmi_cases(metafunc.config.getoption("--iot-data"))
    except (ValueError, KeyError, OSError) as error:
        raise pytest.UsageError(f"Invalid HDMI test data: {error}") from None
    metafunc.parametrize("hdmi_case", cases, ids=[case["id"] for case in cases])


async def test_9220_hdmi_volume(hdmi_device, hdmi_case):
    # 操作：设置音量，取得经回包、状态推送及主动查询复核后的状态。
    after = await hdmi_device.set_volume(hdmi_case["target_volume"])

    # 验证：HDMI 音量必须是整数，并且等于本条数据的预期。
    actual = after["HDMI_audio_status"]
    assert type(actual) is int
    assert actual == hdmi_case["expected_volume"]

    # 验证：其他原本存在的音频通道没有随 HDMI 一起改变。
    if hdmi_case["other_audio_unchanged"]:
        for field in ("IP_broadcast_audio_status", "MIC_audio_status", "iHub_audio_status",
                      "Recorder_audio_status", "Desktop_mike_audio_status"):
            if field in hdmi_device.initial_state:
                assert after.get(field) == hdmi_device.initial_state[field], f"Unrelated audio changed: {field}"
