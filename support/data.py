"""读取 HDMI 用例数据，返回独立字典；不连接设备，不执行测试。"""
import json
import os
from pathlib import Path


def load_hdmi_cases(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        cases = json.load(stream)["cases"]
    if not cases:
        raise ValueError("HDMI test data must contain at least one case")
    resolved = []
    for item in cases:
        case = dict(item)
        if "IOT_HDMI_VOLUME" in os.environ:
            case["target_volume"] = int(os.environ["IOT_HDMI_VOLUME"])
            case["expected_volume"] = case["target_volume"]
        if type(case["target_volume"]) is not int or type(case["expected_volume"]) is not int:
            raise ValueError("HDMI case target/expected volume must be integers")
        if type(case["other_audio_unchanged"]) is not bool:
            raise ValueError("other_audio_unchanged must be a boolean")
        resolved.append(case)
    return resolved
